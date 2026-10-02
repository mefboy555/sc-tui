# sc-tui

soundcloud t-ui client


configurations are create in ~/.config/scplayer/config.json

history into ~/.config/scplayer/histroy.json

playlists creates also in *.json files into ~/.config/scplayer/playlists/


needs: yt-dlp mpv python


BUILDING FROM SCRATH:



pkgs req: python3-dev patchelf ccache pip nuitka

    cd ~/sc-tui
    python3 -m nuitka \
        --standalone \
        --onefile \
        --include-package=scplay \
        --output-filename=scplay \
        --remove-output \
        scplay
