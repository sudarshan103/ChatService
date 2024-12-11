from flask_jwt_extended import JWTManager

from app import create_app

app = create_app()
jwt = JWTManager(app)

if __name__ == '__main__':
    app.run(debug=True)
