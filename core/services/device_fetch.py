"""
core/services/device_fetch.py

Optional: live SSH pull of running-config from a device, instead of file
upload. Only wire this in if you need "connect directly to router" as
a feature.
"""

from netmiko import ConnectHandler


def fetch_config_from_router(ip: str, username: str, password: str = None,
                              key_file: str = None, enable_password: str = None):
    """Connects via SSH and returns (connection, running_config_text)."""
    device = {
        "device_type": "cisco_ios",
        "ip": ip,
        "username": username,
        "timeout": 10,
        "session_timeout": 30,
    }
    if key_file:
        device["use_keys"] = True
        device["key_file"] = key_file
    else:
        device["password"] = password
    if enable_password:
        device["secret"] = enable_password

    connection = ConnectHandler(**device)
    if enable_password:
        connection.enable()
    config_text = connection.send_command("show running-config")
    return connection, config_text