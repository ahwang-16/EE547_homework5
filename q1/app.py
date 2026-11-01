import json
import os
import sys
import time
import datetime
import functools
import threading
from flask import Flask, request, jsonify, abort
from werkzeug.exceptions import HTTPException
import boto3
from boto3.dynamodb.conditions import Key
import jwt

JWT_SECRET = os.environ.get('JWT_SECRET')
if not JWT_SECRET:
    print("Error: JWT_SECRET environment variable is unset or empty.", file=sys.stderr)
    sys.exit(3)

AWS_REGION = os.environ.get('AWS_REGION', 'us-west-2')
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE', 'arxiv-papers')

app = Flask(__name__)

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE)

START_TIME = time.time()
STATS_LOCK = threading.Lock()
REQUEST_COUNTS = {
    "total": 0,
    "by_status": {}
}

USERS = {
    "admin": {"password": "secret", "role": "admin"},
    "viewer": {"password": "readonly", "role": "viewer"}
}

@app.after_request
def after_request(response):
    with STATS_LOCK:
        REQUEST_COUNTS["total"] += 1
        status = str(response.status_code)
        REQUEST_COUNTS["by_status"][status] = REQUEST_COUNTS["by_status"].get(status, 0) + 1
    return response

@app.errorhandler(HTTPException)
def handle_http_exception(e):
    error_message = e.description
    if e.code == 404 and "Paper not found" not in error_message:
        error_message = "Not found"

    response = app.response_class(
        response=json.dumps({"error": error_message}),
        status=e.code,
        mimetype='application/json'
    )
    if e.code == 401:
        response.headers['WWW-Authenticate'] = 'Bearer'
    elif e.code == 405:
        valid_methods = getattr(e, 'valid_methods', None)
        if valid_methods:
            response.headers['Allow'] = ', '.join(valid_methods)
    return response

@app.errorhandler(Exception)
def handle_exception(e):
    return app.response_class(
        response=json.dumps({"error": "Internal Server Error"}),
        status=500,
        mimetype='application/json'
    )

def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            abort(401, description="Missing Authorization header")

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            abort(401, description="Malformed Authorization header")

        token = parts[1]
        try:
            jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            abort(401, description="Expired token")
        except jwt.InvalidSignatureError:
            abort(401, description="Invalid signature")
        except jwt.InvalidTokenError:
            abort(401, description="Invalid token")

        return f(*args, **kwargs)
    return decorated

def parse_limit(req):
    limit_str = req.args.get('limit', 20)
    try:
        limit = int(limit_str)
        if not (1 <= limit <= 100):
            raise ValueError()
        return limit
    except ValueError:
        abort(400, description="limit must be an integer from 1 to 100")

def deduplicate_and_format_papers(items, include_abstract=False):
    seen = set()
    formatted = []
    for item in items:
        if item['arxiv_id'] not in seen:
            seen.add(item['arxiv_id'])
            paper = {
                "arxiv_id": item['arxiv_id'],
                "title": item['title'],
                "authors": item['authors'],
                "published": item['published'],
                "categories": item['categories']
            }
            if include_abstract and 'abstract' in item:
                paper['abstract'] = item['abstract']
            formatted.append(paper)
    return formatted

@app.route('/api/stats', methods=['GET'])
def get_stats():
    uptime = int(time.time() - START_TIME)
    with STATS_LOCK:
        counts = {
            "total": REQUEST_COUNTS["total"],
            "by_status": dict(REQUEST_COUNTS["by_status"])
        }
    return jsonify({
        "status": "healthy",
        "uptime_seconds": uptime,
        "region": AWS_REGION,
        "table": DYNAMODB_TABLE,
        "requests": counts
    })

@app.route('/api/login', methods=['POST'])
def login():
    if not request.is_json:
        abort(400, description="Request body must be JSON")

    data = request.get_json()
    if not isinstance(data, dict):
        abort(400, description="Request body must be a JSON object")

    username = data.get('username')
    password = data.get('password')

    if not isinstance(username, str) or not isinstance(password, str):
        abort(400, description="Missing or invalid string username or password")

    user = USERS.get(username)
    if not user or user['password'] != password:
        abort(401, description="Invalid credentials")

    now = int(time.time())
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + 3600,
        "role": user["role"]
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm='HS256')
    return jsonify({"token": token, "expires_in": 3600})

@app.route('/api/papers', methods=['GET'])
@require_auth
def get_recent_papers():
    category = request.args.get('category')
    if not category:
        abort(400, description="Missing required category parameter")

    limit = parse_limit(request)

    response = table.query(
        KeyConditionExpression=Key('category').eq(category),
        ScanIndexForward=False,
        Limit=limit
    )

    papers = deduplicate_and_format_papers(response.get('Items', []))
    return jsonify({
        "category": category,
        "papers": papers,
        "count": len(papers)
    })

@app.route('/api/papers/<arxiv_id>', methods=['GET'])
@require_auth
def get_paper_detail(arxiv_id):
    response = table.query(
        IndexName='PaperIdIndex',
        KeyConditionExpression=Key('arxiv_id').eq(arxiv_id)
    )
    items = response.get('Items', [])
    if not items:
        abort(404, description=f"Paper not found: {arxiv_id}")

    paper = deduplicate_and_format_papers(items, include_abstract=True)[0]
    return jsonify(paper)

@app.route('/api/papers/author/<author_name>', methods=['GET'])
@require_auth
def get_papers_by_author(author_name):
    response = table.query(
        IndexName='AuthorIndex',
        KeyConditionExpression=Key('author').eq(author_name)
    )
    papers = deduplicate_and_format_papers(response.get('Items', []))

    papers.sort(key=lambda x: x['published'], reverse=True)
    return jsonify({
        "author": author_name,
        "papers": papers,
        "count": len(papers)
    })

@app.route('/api/papers/search', methods=['GET'])
@require_auth
def search_papers():
    category = request.args.get('category')
    start = request.args.get('start')
    end = request.args.get('end')

    if not category or not start or not end:
        abort(400, description="category, start, and end parameters are required")

    try:
        start_date = datetime.datetime.strptime(start, '%Y-%m-%d')
        end_date = datetime.datetime.strptime(end, '%Y-%m-%d')
        if start_date > end_date:
            abort(400, description="start date cannot be after end date")
    except ValueError:
        abort(400, description="start and end must be YYYY-MM-DD")

    start_str = start
    end_str = end + "T23:59:59Z"

    response = table.query(
        KeyConditionExpression=Key('category').eq(category) & Key('published').between(start_str, end_str),
        ScanIndexForward=False
    )

    papers = deduplicate_and_format_papers(response.get('Items', []))
    return jsonify({
        "category": category,
        "start": start,
        "end": end,
        "papers": papers,
        "count": len(papers)
    })

@app.route('/api/papers/keyword/<keyword>', methods=['GET'])
@require_auth
def get_papers_by_keyword(keyword):
    limit = parse_limit(request)

    response = table.query(
        IndexName='KeywordIndex',
        KeyConditionExpression=Key('keyword').eq(keyword),
        ScanIndexForward=False,
        Limit=limit
    )

    papers = deduplicate_and_format_papers(response.get('Items', []))
    return jsonify({
        "keyword": keyword,
        "papers": papers[:limit],
        "count": len(papers[:limit])
    })

@app.route('/api/papers/<arxiv_id>/arxiv', methods=['GET'])
def redirect_to_arxiv(arxiv_id):
    response = table.query(
        IndexName='PaperIdIndex',
        KeyConditionExpression=Key('arxiv_id').eq(arxiv_id)
    )
    if not response.get('Items'):
        abort(404, description=f"Paper not found: {arxiv_id}")

    resp = app.response_class(response="", status=302)
    resp.headers['Location'] = f"https://arxiv.org/abs/{arxiv_id}"
    return resp

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
