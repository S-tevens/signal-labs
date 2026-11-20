"""Collector enrollment (planned).

Target flow: first start exchanges a one-time enrollment token for the collector key,
secret and config, so a new collector registers itself with no manual setup.
For now the key and secret come from environment variables (see .env.example).
"""
