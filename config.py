"""
Configuration management for GEMP Game Analytics.

Reads from INI file with environment variable overrides.
"""

import configparser
import os
from pathlib import Path


class Config:
    """
    Configuration container with INI file and environment variable support.
    
    Environment variables override INI values:
        GEMP_DB_HOST, GEMP_DB_PORT, GEMP_DB_USER, GEMP_DB_PASSWORD, GEMP_DB_NAME
        GEMP_REPLAY_PATH, GEMP_MAPPING_FILE
    """
    
    def __init__(self, config_file: str = 'config.ini'):
        self._parser = configparser.ConfigParser()
        
        # Load from file if exists
        if Path(config_file).exists():
            self._parser.read(config_file)
        
        # Database settings
        self.db_host = self._get('database', 'host', 'GEMP_DB_HOST', 'localhost')
        self.db_port = int(self._get('database', 'port', 'GEMP_DB_PORT', '3306'))
        self.db_user = self._get('database', 'user', 'GEMP_DB_USER', 'gemp')
        self.db_password = self._get('database', 'password', 'GEMP_DB_PASSWORD', '')
        self.db_name = self._get('database', 'name', 'GEMP_DB_NAME', 'gemp_db')
        
        # File paths
        self.replay_base_path = self._get('paths', 'replay_base', 'REPLAY_PATH', '/replay')
        self.mapping_file = self._get('paths', 'mapping_file', 'MAPPING_FILE', 'blueprintMapping.txt')
    
    def _get(self, section: str, key: str, env_var: str, default: str) -> str:
        """
        Get config value with precedence: env var > INI file > default.
        """
        # Environment variable takes precedence
        env_value = os.environ.get(env_var)
        if env_value is not None:
            return env_value
        
        # Then INI file
        try:
            return self._parser.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            pass
        
        # Finally default
        return default
