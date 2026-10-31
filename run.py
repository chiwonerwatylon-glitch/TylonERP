"""
============================================================================
TylonERP - Application Runner
Version: 1.0.0
Brand: Multi-tenant Stock, Revenue & Debtor Management System

This module provides production-ready server launching utilities.
Supports multiple WSGI servers and deployment configurations.

Features:
    - Gunicorn server configuration
    - uWSGI server configuration
    - Development server with hot-reload
    - Production server with worker management
    - Environment validation
    - Database migration automation
    - Port availability checking
    - Graceful shutdown handling
============================================================================
"""

import os
import sys
import time
import socket
import signal
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, List

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Project paths
PROJECT_ROOT = Path(__file__).parent.absolute()
APP_DIR = PROJECT_ROOT / 'app'
LOGS_DIR = PROJECT_ROOT / 'logs'

# ============================================================================
# 1. ENVIRONMENT VALIDATION
# ============================================================================

class EnvironmentValidator:
    """Validate application environment setup."""
    
    @staticmethod
    def check_required_files():
        """Check if required files exist."""
        required_files = [
            'config.py',
            'requirements.txt',
            '.env',
            'app/__init__.py',
        ]
        
        missing = []
        for file in required_files:
            if not (PROJECT_ROOT / file).exists():
                missing.append(file)
        
        if missing:
            logger.warning(f'Missing files: {", ".join(missing)}')
            return False
        
        logger.info('✓ All required files present')
        return True
    
    @staticmethod
    def check_dependencies():
        """Check if Python dependencies are installed."""
        try:
            import flask
            import sqlalchemy
            import flask_jwt_extended
            import flask_cors
            logger.info('✓ All dependencies installed')
            return True
        except ImportError as e:
            logger.error(f'Missing dependency: {str(e)}')
            logger.info('Run: pip install -r requirements.txt')
            return False
    
    @staticmethod
    def check_environment_variables():
        """Check if required environment variables are set."""
        required_vars = [
            'FLASK_ENV',
            'FLASK_DEBUG',
            'SECRET_KEY',
            'DATABASE_URL',
            'JWT_SECRET_KEY',
        ]
        
        missing = []
        for var in required_vars:
            if not os.getenv(var):
                missing.append(var)
        
        if missing:
            logger.warning(f'Missing environment variables: {", ".join(missing)}')
            logger.info('Create .env file with required variables')
            return False
        
        logger.info('✓ All environment variables set')
        return True
    
    @staticmethod
    def validate_all():
        """Run all validation checks."""
        logger.info('Validating environment...')
        
        checks = [
            EnvironmentValidator.check_required_files(),
            EnvironmentValidator.check_dependencies(),
            EnvironmentValidator.check_environment_variables(),
        ]
        
        if all(checks):
            logger.info('✓ Environment validation passed')
            return True
        
        logger.error('✗ Environment validation failed')
        return False


# ============================================================================
# 2. PORT UTILITIES
# ============================================================================

class PortManager:
    """Manage port availability and selection."""
    
    @staticmethod
    def is_port_available(port: int) -> bool:
        """
        Check if a port is available for binding.
        
        Args:
            port (int): Port number to check
            
        Returns:
            bool: True if port is available
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('127.0.0.1', port))
            sock.close()
            return True
        except OSError:
            return False
    
    @staticmethod
    def find_available_port(start_port: int = 5000, max_attempts: int = 10) -> Optional[int]:
        """
        Find an available port starting from start_port.
        
        Args:
            start_port (int): Starting port number
            max_attempts (int): Maximum number of ports to try
            
        Returns:
            int: Available port number or None
        """
        for offset in range(max_attempts):
            port = start_port + offset
            if PortManager.is_port_available(port):
                return port
        
        return None


# ============================================================================
# 3. DATABASE MANAGEMENT
# ============================================================================

class DatabaseManager:
    """Manage database setup and migrations."""
    
    @staticmethod
    def init_database():
        """Initialize database and run migrations."""
        logger.info('Initializing database...')
        
        try:
            os.system('flask db upgrade')
            logger.info('✓ Database initialized')
            return True
        except Exception as e:
            logger.error(f'Failed to initialize database: {str(e)}')
            return False
    
    @staticmethod
    def seed_database():
        """Seed database with initial data."""
        logger.info('Seeding database...')
        
        try:
            os.system('flask seed-db')
            logger.info('✓ Database seeded')
            return True
        except Exception as e:
            logger.error(f'Failed to seed database: {str(e)}')
            return False


# ============================================================================
# 4. SERVER CONFIGURATIONS
# ============================================================================

class ServerConfig:
    """Server configuration management."""
    
    @staticmethod
    def get_gunicorn_config() -> Dict[str, any]:
        """
        Get Gunicorn server configuration.
        
        Returns:
            dict: Gunicorn configuration
        """
        workers = int(os.getenv('GUNICORN_WORKERS', 4))
        threads = int(os.getenv('GUNICORN_THREADS', 2))
        timeout = int(os.getenv('GUNICORN_TIMEOUT', 120))
        
        return {
            'workers': workers,
            'threads': threads,
            'worker_class': 'gthread',
            'worker_connections': 1000,
            'timeout': timeout,
            'keepalive': 5,
            'max_requests': 1000,
            'max_requests_jitter': 100,
            'access_log': str(LOGS_DIR / 'access.log'),
            'error_log': str(LOGS_DIR / 'error.log'),
            'log_level': 'info',
            'bind': f"{os.getenv('SERVER_HOST', '0.0.0.0')}:{os.getenv('SERVER_PORT', 5000)}",
        }
    
    @staticmethod
    def get_uwsgi_config() -> Dict[str, any]:
        """
        Get uWSGI server configuration.
        
        Returns:
            dict: uWSGI configuration
        """
        return {
            'module': 'app:app',
            'master': True,
            'processes': int(os.getenv('UWSGI_PROCESSES', 4)),
            'threads': int(os.getenv('UWSGI_THREADS', 2)),
            'socket': f"{os.getenv('SERVER_HOST', '0.0.0.0')}:{os.getenv('SERVER_PORT', 5000)}",
            'protocol': 'http',
            'daemonize': str(LOGS_DIR / 'uwsgi.log'),
            'pidfile': str(PROJECT_ROOT / 'uwsgi.pid'),
        }


# ============================================================================
# 5. SERVER LAUNCHERS
# ============================================================================

class ServerLauncher:
    """Launch application servers."""
    
    @staticmethod
    def run_development_server(host: str = '127.0.0.1', port: int = 5000, debug: bool = True):
        """
        Run Flask development server.
        
        Args:
            host (str): Host to bind to
            port (int): Port to bind to
            debug (bool): Enable debug mode
            
        Returns:
            None
        """
        logger.info(f'Starting development server on {host}:{port}')
        logger.warning('⚠️  Development server only! Do not use in production!')
        
        os.chdir(PROJECT_ROOT)
        os.system(f'flask run --host {host} --port {port}')
    
    @staticmethod
    def run_gunicorn_server(workers: Optional[int] = None, threads: Optional[int] = None):
        """
        Run Gunicorn WSGI server.
        
        Args:
            workers (int): Number of worker processes
            threads (int): Number of threads per worker
            
        Returns:
            None
        """
        config = ServerConfig.get_gunicorn_config()
        
        if workers:
            config['workers'] = workers
        if threads:
            config['threads'] = threads
        
        # Build gunicorn command
        cmd = ['gunicorn']
        
        for key, value in config.items():
            if isinstance(value, bool):
                if value:
                    cmd.append(f'--{key.replace("_", "-")}')
            else:
                cmd.append(f'--{key.replace("_", "-")}={value}')
        
        cmd.append('app:app')
        
        logger.info(f'Starting Gunicorn server with {config["workers"]} workers')
        logger.info(f'Command: {" ".join(cmd)}')
        
        os.chdir(PROJECT_ROOT)
        os.execvp('gunicorn', cmd)
    
    @staticmethod
    def run_uwsgi_server():
        """
        Run uWSGI server.
        
        Returns:
            None
        """
        config = ServerConfig.get_uwsgi_config()
        
        # Build uwsgi command
        cmd = ['uwsgi']
        
        for key, value in config.items():
            cmd.append(f'--{key}={value}')
        
        logger.info('Starting uWSGI server')
        logger.info(f'Command: {" ".join(cmd)}')
        
        os.chdir(PROJECT_ROOT)
        os.execvp('uwsgi', cmd)
    
    @staticmethod
    def run_production_server(server: str = 'gunicorn', workers: Optional[int] = None):
        """
        Run production server.
        
        Args:
            server (str): Server type ('gunicorn' or 'uwsgi')
            workers (int): Number of workers
            
        Returns:
            None
        """
        # Validate environment
        if not EnvironmentValidator.validate_all():
            logger.error('Environment validation failed. Exiting.')
            sys.exit(1)
        
        # Create logs directory
        LOGS_DIR.mkdir(exist_ok=True)
        
        # Initialize database if needed
        if os.getenv('AUTO_MIGRATE', 'False').lower() == 'true':
            DatabaseManager.init_database()
        
        # Launch server
        if server.lower() == 'gunicorn':
            ServerLauncher.run_gunicorn_server(workers=workers)
        elif server.lower() == 'uwsgi':
            ServerLauncher.run_uwsgi_server()
        else:
            logger.error(f'Unknown server: {server}')
            sys.exit(1)


# ============================================================================
# 6. COMMAND LINE INTERFACE
# ============================================================================

def main():
    """Main command line interface."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='TylonERP Application Runner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run development server
  python run.py dev
  
  # Run production server with Gunicorn
  python run.py prod --server gunicorn --workers 4
  
  # Run with custom host and port
  python run.py dev --host 0.0.0.0 --port 8000
  
  # Initialize database before running
  python run.py prod --init-db
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Development server
    dev_parser = subparsers.add_parser('dev', help='Run development server')
    dev_parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    dev_parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    dev_parser.add_argument('--no-debug', action='store_true', help='Disable debug mode')
    
    # Production server
    prod_parser = subparsers.add_parser('prod', help='Run production server')
    prod_parser.add_argument(
        '--server',
        choices=['gunicorn', 'uwsgi'],
        default='gunicorn',
        help='WSGI server to use'
    )
    prod_parser.add_argument('--workers', type=int, help='Number of workers')
    prod_parser.add_argument('--init-db', action='store_true', help='Initialize database')
    prod_parser.add_argument('--seed-db', action='store_true', help='Seed database')
    
    # Validation
    valid_parser = subparsers.add_parser('validate', help='Validate environment')
    
    # Database
    db_parser = subparsers.add_parser('db', help='Database management')
    db_subparsers = db_parser.add_subparsers(dest='db_command')
    db_subparsers.add_parser('init', help='Initialize database')
    db_subparsers.add_parser('seed', help='Seed database')
    
    args = parser.parse_args()
    
    # Handle commands
    if args.command == 'dev':
        logger.info('Running development server...')
        ServerLauncher.run_development_server(
            host=args.host,
            port=args.port,
            debug=not args.no_debug
        )
    
    elif args.command == 'prod':
        if args.init_db:
            DatabaseManager.init_database()
        if args.seed_db:
            DatabaseManager.seed_database()
        
        ServerLauncher.run_production_server(
            server=args.server,
            workers=args.workers
        )
    
    elif args.command == 'validate':
        if EnvironmentValidator.validate_all():
            logger.info('✓ All checks passed!')
            sys.exit(0)
        else:
            logger.error('✗ Validation failed!')
            sys.exit(1)
    
    elif args.command == 'db':
        if args.db_command == 'init':
            DatabaseManager.init_database()
        elif args.db_command == 'seed':
            DatabaseManager.seed_database()
        else:
            db_parser.print_help()
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
