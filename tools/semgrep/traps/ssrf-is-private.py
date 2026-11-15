import ipaddress
import socket


def allowed(host):
    ip = ipaddress.ip_address(socket.gethostbyname(host))
    # ruleid: ssrf-is-private
    return not ip.is_private


BLOCKED = [ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("64:ff9b::/96")]


def allowed_with_deny_list(host):
    ip = ipaddress.ip_address(socket.gethostbyname(host))
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    # ok: ssrf-is-private
    return not ip.is_private and not any(ip in net for net in BLOCKED)


def allowed_strict(host):
    ip = ipaddress.ip_address(socket.gethostbyname(host))
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    # ok: ssrf-is-private
    return ip.is_global
