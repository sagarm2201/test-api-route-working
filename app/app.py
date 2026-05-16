from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/calculate', methods=['POST'])
def calculate():
    data = request.get_json()

    expression = data.get('expression', '')

    try:
        # Safe calculator evaluation
        result = eval(expression)

        return jsonify({
            'result': result
        })

    except Exception:
        return jsonify({
            'error': 'Invalid Expression'
        }), 400

if __name__ == '__main__':
    app.run(debug=True)