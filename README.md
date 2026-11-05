<div align="center">
  <img src="data/io.github.maxel.Moneo.svg" alt="Icône de Monéo" width="96" height="96">
  <h1>Monéo</h1>
  <p><strong>Une application GNOME pour gérer ton argent simplement.</strong><br>
  Budgets, relevés bancaires, récurrences et objectifs d'épargne : tes données restent sur ton ordinateur.</p>
</div>

Monéo est une application de bureau pour Linux, écrite en Python avec GTK4 et libadwaita. Elle fonctionne sans
compte ni service en ligne : tout est enregistré dans une base SQLite locale.

Le projet en est à sa version 0.1.0 et son interface est en français.

## Fonctionnalités

- **Aperçu** : solde, chiffres du mois, budgets, prochaines échéances et dernières opérations.
- **Opérations** : saisie, recherche, filtres et navigation par mois.
- **Import** : relevés CSV et OFX de ta banque, sans doublon si tu réimportes un fichier.
- **Suivi** : évolution du solde, revenus et dépenses par mois, dépenses par catégorie.
- **Catégories** : les tiennes, avec une couleur et un budget mensuel facultatif.
- **Récurrences** : loyer, salaire et abonnements ajoutés automatiquement à chaque échéance.
- **Objectifs** : suivi de ton épargne et montant à mettre de côté chaque mois.
- **Sauvegarde** : création et restauration depuis le menu principal.

## Installation

### Prérequis

Il te faut Python 3.11 ou plus récent, GTK4, libadwaita 1.7 ou plus récent, et PyGObject.
Ces dépendances sont déjà présentes sur Fedora Workstation. Sinon, installe-les avec la commande de ta distribution :

```sh
sudo dnf install python3-gobject gtk4 libadwaita            # Fedora
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1     # Debian, Ubuntu
sudo pacman -S python-gobject gtk4 libadwaita               # Arch
```

### Récupérer et lancer Monéo

```sh
git clone https://github.com/MaXelDev/Mon-o.git
cd Mon-o
python3 -m moneo
```

### Ajouter Monéo au menu des applications

```sh
./install.sh
```

L'entrée du menu pointe vers ce dossier : ne le déplace pas après l'installation, ou relance `./install.sh` depuis
son nouvel emplacement.

### Désinstaller

```sh
./uninstall.sh           # retire Monéo du menu et garde tes données
./uninstall.sh --purge   # efface aussi tes données, après confirmation
```

Le dossier du projet n'est jamais supprimé par ce script : tu peux l'effacer toi-même ensuite.

## Raccourcis clavier

| Raccourci | Action |
|---|---|
| `Ctrl+N` | Ajouter une opération |
| `Ctrl+I` | Importer un relevé |
| `Ctrl+W` | Fermer la fenêtre |

## Bon à savoir

- **Remboursements** : saisis-les en « Revenu » dans leur catégorie de dépense, ils réduisent alors cette dépense.
- **Rapprochement à l'import** : une opération déjà saisie ou récurrente, de même montant et à 3 jours près,
  est reliée à la ligne du relevé au lieu d'être dupliquée. Le message de fin d'import indique combien.
- **Classement automatique** : un libellé déjà classé reprend sa catégorie à l'import. Classer une opération
  classe aussi les autres opérations sans catégorie portant le même libellé.
- **Objectifs** : l'argent mis de côté reste sur ton compte, il est seulement réservé.
- **Dates des CSV** : toujours lues avec le jour avant le mois, comme dans les banques françaises.

## Données et confidentialité

La base se trouve dans `~/.local/share/moneo/moneo.db`. Elle est lisible par ton seul compte, mais **elle n'est pas
chiffrée** : chiffre ton disque et garde tes sauvegardes en lieu sûr.

Avant une restauration, une copie des données actuelles est conservée dans `moneo.db.avant-restauration`.

## Développement

Les tests utilisent `unittest`, sans dépendance à installer :

```sh
python3 -m unittest discover -s tests -t .
```

Organisation du code :

```text
data/    icône de l'application
moneo/   code de l'application (interface, base de données, import des relevés)
tests/   tests unitaires
```

## Licence

Monéo est distribué sous [licence MIT](LICENSE).
