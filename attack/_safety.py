"""Garde-fou de périmètre — RÈGLE ABSOLUE DU WORKSHOP.

« Toutes les actions offensives restent strictement limitées à votre SI fictif
et aux machines autorisées de votre équipe. Les réseaux du campus, les autres
groupes et les services tiers sont hors périmètre. »

Ces scripts REFUSENT de s'exécuter contre une cible qui n'est pas privée/locale.
Le réseau du consortium est 192.168.137.0/24 (PA mobile RESILIENCE-G<n>).
"""
import ipaddress
import socket
import sys
from urllib.parse import urlparse


def _resolve(host: str) -> str:
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return host


def assert_target_in_scope(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host in ("localhost",) or host.endswith(".localhost") or host.endswith(".test"):
        return
    ip_str = _resolve(host)
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        _refuse(url, f"hote non resolu en IP ({ip_str})")
        return
    # On autorise uniquement loopback + plages privees (dont 192.168.137.0/24).
    if ip.is_loopback or ip.is_private:
        return
    _refuse(url, f"IP publique/hors-perimetre detectee ({ip})")


def _refuse(url: str, reason: str) -> None:
    print("=" * 70, file=sys.stderr)
    print("  REFUS : cible hors du perimetre autorise du workshop.", file=sys.stderr)
    print(f"  Cible : {url}", file=sys.stderr)
    print(f"  Motif : {reason}", file=sys.stderr)
    print("  Ces outils ne visent QUE le SI fictif local du consortium", file=sys.stderr)
    print("  (127.0.0.1 ou 192.168.137.0/24). Aucune autre cible admise.", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    sys.exit(2)
