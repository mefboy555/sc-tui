# sc-tui

soundcloud t-ui client


configurations are create in ~/.config/scplayer/config.json

history into ~/.config/scplayer/histroy.json

playlists creates also in *.json files into ~/.config/scplayer/playlists/


build by nuitka

    python3 -m nuitka \
        --standalone \
        --onefile \
        --include-package=scplay \
        --output-filename=scplay \
        --remove-output \
        __main__.py
