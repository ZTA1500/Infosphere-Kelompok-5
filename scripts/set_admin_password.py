"""Set (or reset) the Infosphere admin password.

    python scripts/set_admin_password.py              # prompts for a password
    python scripts/set_admin_password.py --generate   # creates a strong random one
    python scripts/set_admin_password.py --username alice
    python scripts/set_admin_password.py --print      # print the values for a hosting
                                                      # dashboard's environment variables

Only a salted scrypt hash is written to .env — the password itself is never
stored. The script also creates SECRET_KEY and VISITOR_SALT if they're
missing, and signs out every existing admin session. Restart the server after
running it.
"""
import argparse
import getpass
import os
import secrets
import string
import sys

from werkzeug.security import generate_password_hash

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
ENV_PATH = os.path.join(ROOT, '.env')

WEAK = {'admin', 'admin123', 'password', 'password123', 'infosphere', '12345678',
        '123456789', 'qwerty123', 'letmein', 'changeme', 'welcome1'}


def read_env(path):
    lines, values = [], {}
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f.read().splitlines():
                lines.append(line)
                s = line.strip()
                if s and not s.startswith('#') and '=' in s:
                    k, _, v = s.partition('=')
                    values[k.strip()] = v.strip()
    return lines, values


def write_env(path, lines, updates, remove=()):
    out, seen = [], set()
    for line in lines:
        key = line.split('=', 1)[0].strip() if '=' in line and not line.strip().startswith('#') else None
        if key in remove:
            continue
        if key in updates:
            out.append(f'{key}={updates[key]}')
            seen.add(key)
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f'{k}={v}')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(out).rstrip('\n') + '\n')
    os.replace(tmp, path)


def generate_password(length=20):
    alphabet = string.ascii_letters + string.digits + '-_.!@#%^*'
    while True:
        pw = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw)):
            return pw


def check_strength(pw, username):
    if len(pw) < 12:
        return 'Use at least 12 characters.'
    if pw.lower() in WEAK or pw.lower() == username.lower():
        return 'That password is too common.'
    if len(set(pw)) < 6:
        return 'Use a more varied password.'
    return None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Set the Infosphere admin password.')
    ap.add_argument('--username', help='admin username (default: keep current, or "admin")')
    ap.add_argument('--generate', action='store_true', help='generate a strong random password')
    ap.add_argument('--print', dest='print_only', action='store_true',
                    help="don't touch .env; print the variables to paste into your host's settings")
    args = ap.parse_args()

    lines, values = read_env(ENV_PATH)
    username = args.username or values.get('ADMIN_USER') or 'admin'

    if args.generate:
        password = generate_password()
    else:
        if not sys.stdin.isatty():
            sys.exit('No terminal available for the password prompt — use --generate instead.')
        while True:
            password = getpass.getpass(f'New password for "{username}": ')
            problem = check_strength(password, username)
            if problem:
                print(f'  {problem}')
                continue
            if getpass.getpass('Repeat password: ') != password:
                print('  Passwords did not match.')
                continue
            break

    updates = {
        'ADMIN_USER': username,
        'ADMIN_PASSWORD_HASH': generate_password_hash(password, method='scrypt'),
    }
    if not values.get('SECRET_KEY'):
        updates['SECRET_KEY'] = secrets.token_hex(32)
    if not values.get('VISITOR_SALT'):
        updates['VISITOR_SALT'] = secrets.token_hex(16)
    if not lines:
        lines = ['# Infosphere secrets — never commit this file.']

    if args.print_only:
        print()
        print('Set these environment variables on your host (keep them secret):')
        print()
        for k in ('ADMIN_USER', 'ADMIN_PASSWORD_HASH', 'SECRET_KEY', 'VISITOR_SALT'):
            print(f'{k}={updates.get(k) or values.get(k)}')
        if args.generate:
            print()
            print(f'Admin password (shown once): {password}')
        return

    # Drop any old plaintext password so it doesn't linger on disk.
    write_env(ENV_PATH, lines, updates, remove={'ADMIN_PASSWORD'})

    try:
        from server import db
        if os.path.exists(db.DB_PATH):
            n = db.revoke_all_admin_sessions()
            if n:
                print(f'Signed out {n} existing admin session(s).')
    except Exception:
        pass

    print(f'\nSaved to {ENV_PATH}')
    print(f'  Username: {username}')
    if args.generate:
        print(f'  Password: {password}')
        print('  (shown once — store it in a password manager)')
    print('Restart Infosphere for the change to take effect.')


if __name__ == '__main__':
    main()
