from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
from typing import Dict, List, Optional
import uuid

app = Flask(__name__)
CORS(app)

topics: Dict[str, dict] = {}
ticks: Dict[str, List[dict]] = {}


@app.route('/v1/topics', methods=['POST'])
def create_topic():
    data = request.get_json()

    if not data or 'topic' not in data:
        return jsonify({'error': 'topic field is required'}), 400

    topic_name = data['topic']
    topic_id = str(uuid.uuid4())

    topics[topic_id] = {
        'id': topic_id,
        'topic': topic_name,
        'created_at': datetime.utcnow().isoformat()
    }

    ticks[topic_id] = []

    return jsonify(topics[topic_id]), 201


@app.route('/v1/topics', methods=['GET'])
def get_topics():
    return jsonify(list(topics.values())), 200


@app.route('/v1/topics/<topic_id>/ticks', methods=['GET'])
def get_ticks(topic_id):
    if topic_id not in topics:
        return jsonify({'error': 'Topic not found'}), 404

    return jsonify(ticks.get(topic_id, [])), 200


@app.route('/v1/topics/<topic_id>/bars', methods=['GET'])
def get_bars(topic_id):
    if topic_id not in topics:
        return jsonify({'error': 'Topic not found'}), 404

    frequency = request.args.get('frequency', '5min')
    limit = request.args.get('limit', 100, type=int)

    topic_ticks = ticks.get(topic_id, [])

    bars = aggregate_ticks_to_bars(topic_ticks, frequency, limit)

    return jsonify({
        'frequency': frequency,
        'limit': limit,
        'bars': bars
    }), 200


@app.route('/v1/topics/<topic_id>/digest', methods=['GET'])
def get_digest(topic_id):
    if topic_id not in topics:
        return jsonify({'error': 'Topic not found'}), 404

    topic = topics[topic_id]
    topic_ticks = ticks.get(topic_id, [])

    digest = {
        'topic_id': topic_id,
        'topic_name': topic['topic'],
        'created_at': topic['created_at'],
        'total_ticks': len(topic_ticks),
        'summary': f"Topic '{topic['topic']}' has {len(topic_ticks)} ticks"
    }

    return jsonify(digest), 200


def aggregate_ticks_to_bars(topic_ticks: List[dict], frequency: str, limit: int) -> List[dict]:
    """
    Aggregate ticks into bars based on frequency.
    This is a placeholder implementation.
    """
    bars = []

    return bars[:limit]


@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
