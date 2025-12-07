"""
Location service for resolving user locations to WOEIDs for X trending topics API.

Supports:
- GPS coordinates -> WOEID (nearest city matching)
- IP address -> WOEID (via IP geolocation API)
- Caching to minimize external API calls
"""

from __future__ import annotations

import logging
import math
import requests
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class WOEIDResult:
    """Result of WOEID resolution with location metadata."""
    woeid: int
    location_name: str
    country: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class LocationService:
    """
    Resolves user locations (GPS coordinates or IP addresses) to WOEIDs.

    Uses:
    - Static WOEID map with 45+ major cities worldwide
    - Haversine distance for nearest city matching
    - ipapi.co for IP geolocation (free tier: 1,000 req/day)
    - Caching to reduce external API calls
    """

    # Static WOEID map with major cities worldwide
    # Format: { "City Name": { "woeid": int, "lat": float, "lon": float, "country": str } }
    WOEID_MAP = {
        "Worldwide": {"woeid": 1, "lat": 0.0, "lon": 0.0, "country": "Global"},

        # United States
        "New York": {"woeid": 2459115, "lat": 40.7128, "lon": -74.0060, "country": "United States"},
        "Los Angeles": {"woeid": 2442047, "lat": 34.0522, "lon": -118.2437, "country": "United States"},
        "Chicago": {"woeid": 2379574, "lat": 41.8781, "lon": -87.6298, "country": "United States"},
        "Houston": {"woeid": 2424766, "lat": 29.7604, "lon": -95.3698, "country": "United States"},
        "Phoenix": {"woeid": 2471390, "lat": 33.4484, "lon": -112.0740, "country": "United States"},
        "Philadelphia": {"woeid": 2471217, "lat": 39.9526, "lon": -75.1652, "country": "United States"},
        "San Antonio": {"woeid": 2487796, "lat": 29.4241, "lon": -98.4936, "country": "United States"},
        "San Diego": {"woeid": 2487889, "lat": 32.7157, "lon": -117.1611, "country": "United States"},
        "Dallas": {"woeid": 2388929, "lat": 32.7767, "lon": -96.7970, "country": "United States"},
        "San Jose": {"woeid": 2488042, "lat": 37.3382, "lon": -121.8863, "country": "United States"},
        "Austin": {"woeid": 2357536, "lat": 30.2672, "lon": -97.7431, "country": "United States"},
        "Jacksonville": {"woeid": 2428344, "lat": 30.3322, "lon": -81.6557, "country": "United States"},
        "San Francisco": {"woeid": 2487956, "lat": 37.7749, "lon": -122.4194, "country": "United States"},
        "Columbus": {"woeid": 2383660, "lat": 39.9612, "lon": -82.9988, "country": "United States"},
        "Indianapolis": {"woeid": 2427032, "lat": 39.7684, "lon": -86.1581, "country": "United States"},
        "Seattle": {"woeid": 2490383, "lat": 47.6062, "lon": -122.3321, "country": "United States"},
        "Denver": {"woeid": 2391279, "lat": 39.7392, "lon": -104.9903, "country": "United States"},
        "Washington DC": {"woeid": 2514815, "lat": 38.9072, "lon": -77.0369, "country": "United States"},
        "Boston": {"woeid": 2367105, "lat": 42.3601, "lon": -71.0589, "country": "United States"},
        "Nashville": {"woeid": 2457170, "lat": 36.1627, "lon": -86.7816, "country": "United States"},
        "Detroit": {"woeid": 2391585, "lat": 42.3314, "lon": -83.0458, "country": "United States"},
        "Portland": {"woeid": 2475687, "lat": 45.5152, "lon": -122.6784, "country": "United States"},
        "Las Vegas": {"woeid": 2436704, "lat": 36.1699, "lon": -115.1398, "country": "United States"},
        "Miami": {"woeid": 2450022, "lat": 25.7617, "lon": -80.1918, "country": "United States"},
        "Atlanta": {"woeid": 2357024, "lat": 33.7490, "lon": -84.3880, "country": "United States"},

        # International
        "London": {"woeid": 44418, "lat": 51.5074, "lon": -0.1278, "country": "United Kingdom"},
        "Paris": {"woeid": 615702, "lat": 48.8566, "lon": 2.3522, "country": "France"},
        "Tokyo": {"woeid": 1118370, "lat": 35.6762, "lon": 139.6503, "country": "Japan"},
        "Berlin": {"woeid": 638242, "lat": 52.5200, "lon": 13.4050, "country": "Germany"},
        "Madrid": {"woeid": 766273, "lat": 40.4168, "lon": -3.7038, "country": "Spain"},
        "Rome": {"woeid": 721943, "lat": 41.9028, "lon": 12.4964, "country": "Italy"},
        "Toronto": {"woeid": 4118, "lat": 43.6532, "lon": -79.3832, "country": "Canada"},
        "Sydney": {"woeid": 1105779, "lat": -33.8688, "lon": 151.2093, "country": "Australia"},
        "Mumbai": {"woeid": 2295411, "lat": 19.0760, "lon": 72.8777, "country": "India"},
        "São Paulo": {"woeid": 455827, "lat": -23.5505, "lon": -46.6333, "country": "Brazil"},
        "Mexico City": {"woeid": 116545, "lat": 19.4326, "lon": -99.1332, "country": "Mexico"},
        "Seoul": {"woeid": 1132599, "lat": 37.5665, "lon": 126.9780, "country": "South Korea"},
        "Moscow": {"woeid": 2122265, "lat": 55.7558, "lon": 37.6173, "country": "Russia"},
        "Istanbul": {"woeid": 2344116, "lat": 41.0082, "lon": 28.9784, "country": "Turkey"},
        "Shanghai": {"woeid": 2151849, "lat": 31.2304, "lon": 121.4737, "country": "China"},
        "Singapore": {"woeid": 1062617, "lat": 1.3521, "lon": 103.8198, "country": "Singapore"},
        "Hong Kong": {"woeid": 2295410, "lat": 22.3193, "lon": 114.1694, "country": "Hong Kong"},
        "Dubai": {"woeid": 1940345, "lat": 25.2048, "lon": 55.2708, "country": "United Arab Emirates"},
        "Bangkok": {"woeid": 1225448, "lat": 13.7563, "lon": 100.5018, "country": "Thailand"},
        "Amsterdam": {"woeid": 727232, "lat": 52.3676, "lon": 4.9041, "country": "Netherlands"},
        "Barcelona": {"woeid": 753692, "lat": 41.3851, "lon": 2.1734, "country": "Spain"},
        "Dublin": {"woeid": 560743, "lat": 53.3498, "lon": -6.2603, "country": "Ireland"},
        "Lisbon": {"woeid": 742676, "lat": 38.7223, "lon": -9.1393, "country": "Portugal"},
        "Vienna": {"woeid": 551801, "lat": 48.2082, "lon": 16.3738, "country": "Austria"},
        "Brussels": {"woeid": 968019, "lat": 50.8503, "lon": 4.3517, "country": "Belgium"},
    }

    def __init__(self):
        """Initialize the location service with caching."""
        # Cache IP lookups for 24 hours
        self._ip_cache: Dict[str, Tuple[WOEIDResult, datetime]] = {}
        self._ip_cache_ttl = timedelta(hours=24)

        # Cache coordinate lookups for 7 days (locations don't change)
        self._coord_cache: Dict[Tuple[float, float], Tuple[WOEIDResult, datetime]] = {}
        self._coord_cache_ttl = timedelta(days=7)

        logger.info(f"LocationService initialized with {len(self.WOEID_MAP)} cities")

    def _haversine_distance(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float
    ) -> float:
        """
        Calculate the great circle distance between two points on Earth.

        Returns distance in kilometers.
        """
        # Convert to radians
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        # Haversine formula
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
        c = 2 * math.asin(math.sqrt(a))

        # Earth's radius in kilometers
        r = 6371

        return c * r

    def resolve_woeid_from_coordinates(
        self,
        latitude: float,
        longitude: float
    ) -> WOEIDResult:
        """
        Resolve WOEID from GPS coordinates by finding the nearest city.

        Args:
            latitude: Latitude (-90 to 90)
            longitude: Longitude (-180 to 180)

        Returns:
            WOEIDResult with nearest city
        """
        # Check cache
        cache_key = (round(latitude, 4), round(longitude, 4))  # Round to ~10m precision
        if cache_key in self._coord_cache:
            result, cached_at = self._coord_cache[cache_key]
            if datetime.now(timezone.utc) - cached_at < self._coord_cache_ttl:
                logger.debug(f"Cache hit for coordinates {latitude}, {longitude}")
                return result

        # Find nearest city
        nearest_city = None
        nearest_distance = float('inf')

        for city_name, city_data in self.WOEID_MAP.items():
            if city_name == "Worldwide":  # Skip global entry
                continue

            distance = self._haversine_distance(
                latitude, longitude,
                city_data["lat"], city_data["lon"]
            )

            if distance < nearest_distance:
                nearest_distance = distance
                nearest_city = (city_name, city_data)

        if nearest_city is None:
            # Fallback to Worldwide
            logger.warning(f"No nearest city found for {latitude}, {longitude}, using Worldwide")
            city_name = "Worldwide"
            city_data = self.WOEID_MAP["Worldwide"]
        else:
            city_name, city_data = nearest_city
            logger.info(
                f"Resolved coordinates ({latitude}, {longitude}) to {city_name} "
                f"({nearest_distance:.1f} km away)"
            )

        result = WOEIDResult(
            woeid=city_data["woeid"],
            location_name=city_name,
            country=city_data["country"],
            latitude=latitude,
            longitude=longitude
        )

        # Cache result
        self._coord_cache[cache_key] = (result, datetime.now(timezone.utc))

        return result

    def resolve_woeid_from_ip(
        self,
        ip_address: str
    ) -> WOEIDResult:
        """
        Resolve WOEID from IP address using IP geolocation service.

        Uses ipapi.co free tier (1,000 requests/day).

        Args:
            ip_address: IP address to geolocate

        Returns:
            WOEIDResult based on IP location
        """
        # Check cache
        if ip_address in self._ip_cache:
            result, cached_at = self._ip_cache[ip_address]
            if datetime.now(timezone.utc) - cached_at < self._ip_cache_ttl:
                logger.debug(f"Cache hit for IP {ip_address}")
                return result

        try:
            # Call ipapi.co
            url = f"https://ipapi.co/{ip_address}/json/"
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                data = response.json()

                # Check for error in response
                if "error" in data:
                    logger.warning(f"IP geolocation error for {ip_address}: {data.get('reason', 'unknown')}")
                    raise Exception("IP geolocation failed")

                # Extract coordinates
                latitude = data.get("latitude")
                longitude = data.get("longitude")

                if latitude is None or longitude is None:
                    logger.warning(f"No coordinates returned for IP {ip_address}")
                    raise Exception("No coordinates in response")

                logger.info(
                    f"IP {ip_address} geolocated to {data.get('city', 'unknown')}, "
                    f"{data.get('country_name', 'unknown')} ({latitude}, {longitude})"
                )

                # Resolve coordinates to WOEID
                result = self.resolve_woeid_from_coordinates(latitude, longitude)

                # Cache result
                self._ip_cache[ip_address] = (result, datetime.now(timezone.utc))

                return result
            else:
                logger.warning(f"IP geolocation failed with status {response.status_code}")
                raise Exception(f"HTTP {response.status_code}")

        except Exception as e:
            logger.warning(f"Failed to geolocate IP {ip_address}: {e}, using Worldwide")

            # Fallback to Worldwide
            result = WOEIDResult(
                woeid=1,
                location_name="Worldwide",
                country="Global",
                latitude=None,
                longitude=None
            )

            # Don't cache failures
            return result

    def get_woeid_by_name(self, location_name: str) -> Optional[WOEIDResult]:
        """
        Get WOEID by exact location name match.

        Args:
            location_name: City name (case-insensitive)

        Returns:
            WOEIDResult if found, None otherwise
        """
        # Case-insensitive lookup
        for city_name, city_data in self.WOEID_MAP.items():
            if city_name.lower() == location_name.lower():
                return WOEIDResult(
                    woeid=city_data["woeid"],
                    location_name=city_name,
                    country=city_data["country"],
                    latitude=city_data["lat"],
                    longitude=city_data["lon"]
                )

        return None

    def list_available_locations(self) -> list[dict]:
        """
        Get list of all available locations.

        Returns:
            List of dicts with location metadata
        """
        locations = []
        for city_name, city_data in self.WOEID_MAP.items():
            locations.append({
                "name": city_name,
                "woeid": city_data["woeid"],
                "country": city_data["country"],
                "latitude": city_data["lat"],
                "longitude": city_data["lon"]
            })

        return sorted(locations, key=lambda x: x["name"])
