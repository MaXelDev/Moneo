#!/bin/sh
# Ajoute Monéo au menu des applications de l'utilisateur courant.
# Les fichiers de l'appli restent dans ce dossier : ne le déplace pas après l'installation.
set -eu

APP_ID="io.github.maxel.Moneo"
PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPLICATIONS="$DATA_HOME/applications"
ICONS="$DATA_HOME/icons/hicolor/scalable/apps"

mkdir -p "$APPLICATIONS" "$ICONS"
cp "$PROJECT_DIR/data/$APP_ID.svg" "$ICONS/$APP_ID.svg"

cat > "$APPLICATIONS/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Monéo
Comment=Gère ton argent simplement
Exec=python3 -m moneo
Path=$PROJECT_DIR
Icon=$APP_ID
Terminal=false
Categories=Office;Finance;
Keywords=argent;budget;banque;finance;dépenses;
StartupNotify=true
EOF

command -v update-desktop-database >/dev/null && update-desktop-database "$APPLICATIONS" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$DATA_HOME/icons/hicolor" 2>/dev/null || true

echo "Monéo est installé : cherche-le dans le menu des applications."
