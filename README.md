# Monéo

Application GTK4 pour gérer son argent sur GNOME. Tes données restent sur ton ordinateur.

## Lancer l'application

Python 3.11+, GTK4, libadwaita et PyGObject suffisent. Ils sont déjà présents sur Fedora Workstation.
Sinon : `sudo dnf install python3-gobject gtk4 libadwaita`.

```sh
python3 -m moneo     # lancer depuis ce dossier
./install.sh         # ajouter Monéo au menu des applications
./uninstall.sh       # retirer Monéo du menu, en gardant tes données
```

Pour effacer aussi tes données, lance `./uninstall.sh --purge` : le script demande confirmation avant de les supprimer.
Le dossier du projet n'est jamais supprimé.

## Fonctionnalités

- **Aperçu** : solde, chiffres du mois, budgets, prochaines échéances, dernières opérations.
- **Opérations** : saisie, recherche, filtres, navigation par mois (`Ctrl+N` pour ajouter).
- **Import** : relevés CSV et OFX de ta banque (`Ctrl+I`), sans doublon si tu réimportes un fichier.
- **Suivi** : évolution du solde, revenus et dépenses par mois, dépenses par catégorie.
- **Catégories** : les tiennes, avec une couleur et un budget mensuel facultatif.
- **Récurrences** : loyer, salaire, abonnements ajoutés automatiquement à chaque échéance.
- **Objectifs** : suivi de ton épargne et montant à mettre de côté chaque mois.
- **Sauvegarde** : création et restauration depuis le menu principal.

## Bon à savoir

- **Remboursements** : saisis-les en « Revenu » dans leur catégorie de dépense, ils réduisent alors cette dépense.
- **Rapprochement à l'import** : une opération déjà saisie ou récurrente, de même montant et à 3 jours près,
  est reliée à la ligne du relevé au lieu d'être dupliquée. Le message de fin d'import indique combien.
- **Classement automatique** : un libellé déjà classé reprend sa catégorie à l'import. Classer une opération
  classe aussi les autres opérations sans catégorie portant le même libellé.
- **Objectifs** : l'argent mis de côté reste sur ton compte, il est seulement réservé.
- **Dates des CSV** : toujours lues avec le jour avant le mois, comme dans les banques françaises.

## Données

La base se trouve dans `~/.local/share/moneo/moneo.db`, lisible par ton seul compte mais **pas chiffrée**.
Chiffre ton disque et garde tes sauvegardes en lieu sûr. Avant une restauration, une copie des données
actuelles est conservée dans `moneo.db.avant-restauration`.

## Tests

```sh
python3 -m unittest discover -s tests -t .
```
