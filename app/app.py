from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient

import bcrypt
import jwt
import datetime
import ast
import operator

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

app.config['SECRET_KEY'] = 'myverystrongsecretkey123456789'

CORS(app)

# RATE LIMITER
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per day", "20 per minute"]
)

# MongoDB Connection
client = MongoClient("mongodb://localhost:27017")

# Database
db = client["calculatorDB"]

# Collections
history_collection = db["history"]

users_collection = db["users"]

activity_collection = db["activity_logs"]

logs_collection = db["logs"]


# =========================
# SAFE OPERATORS
# =========================
operators = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg
}


# =========================
# SAFE EVALUATION
# =========================
def safe_eval(node):

    if isinstance(node, ast.Constant):
        return node.value

    elif isinstance(node, ast.Num):
        return node.n

    elif isinstance(node, ast.BinOp):

        if type(node.op) not in operators:
            raise TypeError("Invalid Operator")

        left = safe_eval(node.left)

        right = safe_eval(node.right)

        return operators[type(node.op)](
            left,
            right
        )

    elif isinstance(node, ast.UnaryOp):

        if type(node.op) not in operators:
            raise TypeError("Invalid Unary Operator")

        return operators[type(node.op)](
            safe_eval(node.operand)
        )

    else:
        raise TypeError("Unsupported Expression")


# =========================
# ADMIN CHECK
# =========================
def is_admin(decoded):

    if not decoded:
        return False

    return decoded.get('role') == 'admin'


# =========================
# VERIFY TOKEN
# =========================
def verify_token(request):

    auth_header = request.headers.get(
        'Authorization'
    )

    if not auth_header:
        return None

    try:

        token = auth_header.split(" ")[1]

        decoded = jwt.decode(
            token,
            app.config['SECRET_KEY'],
            algorithms=["HS256"]
        )

        return decoded

    except jwt.ExpiredSignatureError:
        return None

    except jwt.InvalidTokenError:
        return None

def log_activity(username, action):

    activity_collection.insert_one({
        'username': username,
        'action': action,
        'createdAt': datetime.datetime.utcnow()
    })

# =========================
# REGISTER API
# =========================
@app.route('/register', methods=['POST'])
def register():

    data = request.get_json()

    username = data.get(
        'username',
        ''
    ).strip()

    password = data.get(
        'password',
        ''
    ).strip()

    if not username or not password:

        return jsonify({
            'error':
            'Username and password required'
        }), 400

    if len(password) < 4:

        return jsonify({
            'error':
            'Password too short'
        }), 400

    existing_user = users_collection.find_one({
        'username': username
    })

    if existing_user:

        return jsonify({
            'error':
            'User already exists'
        }), 400

    hashed_password = bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    )

    users_collection.insert_one({
        'username': username,
        'password': hashed_password,
        'role': 'user',
        'blocked': False,
        'createdAt': datetime.datetime.utcnow()
    })

    return jsonify({
        'message':
        'Registration Successful'
    })


# =========================
# LOGIN API
# =========================
@app.route('/login', methods=['POST'])
def login():

    data = request.get_json()

    username = data.get(
        'username',
        ''
    ).strip()

    password = data.get(
        'password',
        ''
    ).strip()

    user = users_collection.find_one({
        'username': username
    })

    # BLOCK CHECK
    if user and user.get('blocked'):

        return jsonify({
            'error':
            'User blocked by admin'
        }), 403

    # PASSWORD VERIFY
    if user and bcrypt.checkpw(
        password.encode('utf-8'),
        user['password']
    ):

        token = jwt.encode({
            'username': username,
            'role': user['role'],
            'exp':
            datetime.datetime.utcnow()
            + datetime.timedelta(hours=1)
        },
        app.config['SECRET_KEY'],
        algorithm="HS256")

        # SAVE LOG
        logs_collection.insert_one({
            'username': username,
            'action': 'Login',
            'createdAt':
            datetime.datetime.utcnow()
        })
        
        log_activity(username, "User Logged In")

        return jsonify({
            'token': token
        })

    return jsonify({
        'error':
        'Invalid Credentials'
    }), 401


# =========================
# CALCULATE API
# =========================
@limiter.limit("10 per minute")
@app.route('/calculate', methods=['POST'])
def calculate():

    decoded = verify_token(request)

    if not decoded:

        return jsonify({
            'error':
            'Unauthorized'
        }), 401

    data = request.get_json()

    expression = data.get(
        'expression',
        ''
    ).strip()

    username = decoded['username']

    if not expression:

        return jsonify({
            'error':
            'Expression required'
        }), 400

    try:

        parsed = ast.parse(
            expression,
            mode='eval'
        )

        result = safe_eval(parsed.body)
        
        log_activity(
    username,
    f"Calculated: {expression}"
)

        history_collection.insert_one({
            'username': username,
            'expression': expression,
            'result': result,
            'createdAt':
            datetime.datetime.utcnow()
        })

        # SAVE LOG
        logs_collection.insert_one({
            'username': username,
            'action':
            f'Calculated: {expression}',
            'createdAt':
            datetime.datetime.utcnow()
        })

        return jsonify({
            'result': result
        })

    except ZeroDivisionError:

        return jsonify({
            'error':
            'Division by zero not allowed'
        }), 400

    except Exception:

        return jsonify({
            'error':
            'Invalid Expression'
        }), 400


# =========================
# USER HISTORY
# =========================
@app.route('/history', methods=['GET'])
def get_history():

    decoded = verify_token(request)

    if not decoded:

        return jsonify({
            'error':
            'Unauthorized'
        }), 401

    username = decoded['username']

    page = int(
        request.args.get('page', 1)
    )

    limit = int(
        request.args.get('limit', 5)
    )

    skip = (page - 1) * limit

    history = history_collection.find({
        'username': username
    }).sort(
        'createdAt',
        -1
    ).skip(skip).limit(limit)

    result = []

    for item in history:

        result.append({
            'expression':
            item.get('expression'),

            'result':
            item.get('result'),

            'createdAt':
            item.get('createdAt')
        })

    return jsonify(result)


# =========================
# DELETE USER HISTORY
# =========================
@app.route('/history', methods=['DELETE'])
def delete_history():

    decoded = verify_token(request)

    if not decoded:

        return jsonify({
            'error':
            'Unauthorized'
        }), 401

    username = decoded['username']
    
    log_activity(
    username,
    "Deleted History"
)

    history_collection.delete_many({
        'username': username
    })

    return jsonify({
        'message':
        'User history deleted'
    })


# =========================
# ADMIN HISTORY
# =========================
@app.route('/admin/history', methods=['GET'])
def admin_history():

    decoded = verify_token(request)

    if not is_admin(decoded):

        return jsonify({
            'error':
            'Admin only'
        }), 403

    history = history_collection.find().sort(
        'createdAt',
        -1
    )

    result = []

    for item in history:

        result.append({
            'username':
            item.get('username'),

            'expression':
            item.get('expression'),

            'result':
            item.get('result'),

            'createdAt':
            item.get('createdAt')
        })

    return jsonify(result)


# =========================
# ADMIN DELETE HISTORY
# =========================
@app.route('/admin/history', methods=['DELETE'])
def admin_delete_history():

    decoded = verify_token(request)

    if not is_admin(decoded):

        return jsonify({
            'error':
            'Admin only'
        }), 403

    history_collection.delete_many({})

    return jsonify({
        'message':
        'All history deleted'
    })


# =========================
# GET USERS
# =========================
@app.route('/admin/users', methods=['GET'])
def get_users():

    decoded = verify_token(request)

    if not is_admin(decoded):

        return jsonify({
            'error':
            'Admin only'
        }), 403

    users = users_collection.find()

    result = []

    for user in users:

        result.append({
            'username':
            user.get('username'),

            'role':
            user.get('role', 'user'),

            'blocked':
            user.get('blocked', False)
        })

    return jsonify(result)


# =========================
# BLOCK USER
# =========================
@app.route('/admin/block/<username>',
methods=['PUT'])
def block_user(username):

    decoded = verify_token(request)

    if not is_admin(decoded):

        return jsonify({
            'error':
            'Admin only'
        }), 403

    users_collection.update_one(
        {'username': username},
        {
            '$set': {
                'blocked': True
            }
        }
    )

    return jsonify({
        'message':
        'User blocked'
    })


# =========================
# UNBLOCK USER
# =========================
@app.route('/admin/unblock/<username>',
methods=['PUT'])
def unblock_user(username):

    decoded = verify_token(request)

    if not is_admin(decoded):

        return jsonify({
            'error':
            'Admin only'
        }), 403

    users_collection.update_one(
        {'username': username},
        {
            '$set': {
                'blocked': False
            }
        }
    )

    return jsonify({
        'message':
        'User unblocked'
    })


# =========================
# ADMIN LOGS
# =========================
@app.route('/admin/logs', methods=['GET'])
def get_logs():

    decoded = verify_token(request)

    if not is_admin(decoded):

        return jsonify({
            'error':
            'Admin only'
        }), 403

    logs = logs_collection.find().sort(
        'createdAt',
        -1
    )

    result = []

    for log in logs:

        result.append({
            'username':
            log.get('username'),

            'action':
            log.get('action'),

            'createdAt':
            log.get('createdAt')
        })

    return jsonify(result)

# =========================
# ADMIN ACTIVITY LOGS
# =========================
@app.route('/admin/activity', methods=['GET'])
def get_activity_logs():

    decoded = verify_token(request)

    if not is_admin(decoded):

        return jsonify({
            'error': 'Admin only'
        }), 403

    logs = activity_collection.find().sort(
        'createdAt',
        -1
    )

    result = []

    for log in logs:

        result.append({
            'username': log.get('username'),
            'action': log.get('action'),
            'createdAt': log.get('createdAt')
        })

    return jsonify(result)

# =========================
# RUN SERVER
# =========================
if __name__ == '__main__':
    app.run(debug=True)