"""Точка входа: python3 -m scplay [запрос] [-u пользователь]"""

import argparse

from .app import App


def main():
    parser = argparse.ArgumentParser(
        prog="scplay",
        description="Терминальный плеер SoundCloud",
    )
    parser.add_argument("query", nargs="*",
                        help="запрос для поиска или URL плейлиста")
    parser.add_argument("-u", "--user",
                        help="войти под указанным пользователем")
    args = parser.parse_args()

    App(username=args.user).run(
        initial_query=" ".join(args.query) or None
    )


main()
