#!/bin/sh
# Retire Monéo du menu des applications de l'utilisateur courant.
# Le dossier du projet et les données sont conservés.
# Avec --purge, les données sont aussi effacées, après confirmation.
set -eu

APP_ID="io.github.maxel.Moneo"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPLICATIONS="$DATA_HOME/applications"
ICONS="$DATA_HOME/icons/hicolor/scalable/apps"
USER_DATA="$DATA_HOME/moneo"

case "${1:-}:$#" in
    :0) PURGE=false ;;
    --purge:1) PURGE=true ;;
    *)
        echo "Utilisation : $0 [--purge]" >&2
        exit 2
        ;;
esac

rm -f "$APPLICATIONS/$APP_ID.desktop" "$ICONS/$APP_ID.svg"

command -v update-desktop-database >/dev/null && update-desktop-database "$APPLICATIONS" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$DATA_HOME/icons/hicolor" 2>/dev/null || true

echo "Monéo est retiré du menu des applications."

if [ "$PURGE" = false ]; then
    [ -d "$USER_DATA" ] && echo "Tes données sont conservées dans $USER_DATA."
    exit 0
fi

if [ ! -d "$USER_DATA" ]; then
    echo "Aucune donnée à effacer."
    exit 0
fi

echo "Le dossier $USER_DATA et tout ce qu'il contient vont être effacés définitivement."
printf "Écris « oui » pour confirmer : "
read -r ANSWER || ANSWER=""

if [ "$ANSWER" = "oui" ]; then
    rm -rf -- "$USER_DATA"
    echo "Tes données sont effacées."
else
    echo "Rien n'a été effacé : tes données sont conservées dans $USER_DATA."
fi
