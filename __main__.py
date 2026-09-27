"""Точка входа: python3 -m scplay [запрос]"""
import sys

from .app import App


def main():
    query = " ".join(sys.argv[1:]) or None
    App().run(initial_query=query)


main()
