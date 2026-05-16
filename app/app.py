from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient

app = Flask(__name__)
CORS(app)

# MongoDB Connection
client = MongoClient("mongodb://localhost:27017")

# Database
db = client["calculatorDB"]

# Collection
history_collection = db["history"]

# POST API
@app.route('/calculate', methods=['POST'])
def calculate():

    data = request.get_json()

    expression = data.get('expression', '')

    try:

        result = eval(expression)

        # Save to MongoDB
        history_collection.insert_one({
            'expression': expression,
            'result': result
        })

        return jsonify({
            'result': result
        })

    except Exception:

        return jsonify({
            'error': 'Invalid Expression'
        }), 400

# GET API
@app.route('/history', methods=['GET'])
def get_history():

    history = []

    data = history_collection.find()

    for item in data:

        history.append({
            'expression': item['expression'],
            'result': item['result']
        })

    return jsonify(history)

# DELETE API
@app.route('/history', methods=['DELETE'])
def delete_history():

    history_collection.delete_many({})

    return jsonify({
        'message': 'History Deleted'
    })

if __name__ == '__main__':
    app.run(debug=True)