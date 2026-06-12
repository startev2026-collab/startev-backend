import os
import sys

# Ensure the current directory is in sys.path so modules like supabase_client can be found
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from config import Config

from routes.auth import auth_bp
from routes.users import users_bp
from routes.stores import stores_bp
from routes.bikes import bikes_bp
from routes.employees import employees_bp
from routes.rentals import rentals_bp
from routes.payments import payments_bp
from routes.admin import admin_bp
from routes.deposits import deposits_bp


def create_app():
    """Application factory."""
    app = Flask(__name__)

    # Config
    app.config["JWT_SECRET_KEY"] = Config.JWT_SECRET_KEY
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = Config.JWT_ACCESS_TOKEN_EXPIRES
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB upload limit

    # Extensions
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    JWTManager(app)

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(users_bp, url_prefix="/api/users")
    app.register_blueprint(stores_bp, url_prefix="/api/stores")
    app.register_blueprint(bikes_bp, url_prefix="/api/bikes")
    app.register_blueprint(employees_bp, url_prefix="/api/employees")
    app.register_blueprint(rentals_bp, url_prefix="/api/rentals")
    app.register_blueprint(payments_bp, url_prefix="/api/payments")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(deposits_bp, url_prefix="/api/deposits")

    # Health check
    @app.route("/api/health")
    def health():
        return {"status": "ok", "message": "Bike Rental API is running"}

    # Error handlers
    @app.errorhandler(400)
    def bad_request(e):
        return {"error": "Bad request", "message": str(e)}, 400

    @app.errorhandler(404)
    def not_found(e):
        return {"error": "Not found", "message": str(e)}, 404

    @app.errorhandler(413)
    def request_entity_too_large(e):
        return {
            "error": "File upload limit exceeded",
            "message": "The total size of uploaded files exceeds the 32MB limit. Please upload smaller files or compress them."
        }, 413

    @app.errorhandler(500)
    def server_error(e):
        return {"error": "Internal server error", "message": str(e)}, 500

    return app

# Expose the WSGI app object globally for Gunicorn and Waitress
app = create_app()

if __name__ == "__main__":
    import sys

    if "--debug" in sys.argv:
        # Development mode with auto-reload
        app.run(debug=True, port=5000, threaded=True)
    else:
        # Production-grade multi-threaded server
        from waitress import serve

        print("=" * 50)
        print("  StartEV API — Production Server (Waitress)")
        print("  Listening on http://127.0.0.1:5000")
        print("  Threads: 16")
        print("  Use --debug flag for development mode")
        print("=" * 50)
        serve(app, host="127.0.0.1", port=5000, threads=16)

