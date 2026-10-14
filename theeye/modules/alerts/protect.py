"""Chiffre (DPAPI) le mot de passe MySQL à placer dans data/config.json (modules.alerts.db.password_enc).

Usage, avec le compte Windows qui exécute The Eye :  python -m theeye.modules.alerts.protect
"""
import getpass
import sys

from ...core.process import Runner


def main() -> int:
    secret = getpass.getpass("Mot de passe MySQL : ")
    if not secret:
        print("Mot de passe vide.")
        return 1
    r = Runner().powershell("ConvertTo-SecureString $env:EYE_PW -AsPlainText -Force | ConvertFrom-SecureString", 20,
                            {"EYE_PW": secret})
    if not r.ok:
        print("Échec du chiffrement :", r.err.strip())
        return 1
    print('\nÀ coller dans "modules" > "alerts" > "db" :\n  "password_enc": "' + r.out.strip() + '"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
