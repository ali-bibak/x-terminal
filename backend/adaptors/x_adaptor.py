import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

class XAdaptor:
    BASE_URL = "https://api.x.com/2/tweets/search/recent/"

    def __init__(self, bearer_token: str):
        self.bearer_token = bearer_token
        

