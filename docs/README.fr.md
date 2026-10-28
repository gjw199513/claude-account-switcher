[English](../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · Français · [Deutsch](README.de.md)

# Changement de compte Claude

Une petite application macOS non officielle pour changer de compte Claude Desktop tout en conservant la liste locale des sessions Code. Chaque compte est connecté séparément et une seule fenêtre Claude est utilisée à la fois.

## Installation

Il faut macOS, Claude Desktop dans `/Applications`, Xcode Command Line Tools et `/usr/bin/python3` 3.9 ou plus récent.

```sh
git clone https://github.com/gjw199513/claude-account-switcher.git
cd claude-account-switcher
./install.sh
```

Ouvrez **Claude Account Switcher** depuis `~/Applications`. L’interface suit la langue du système : anglais, chinois simplifié, japonais, coréen, espagnol, français ou allemand.

## Utilisation

1. Le profil Claude actuel est le **compte A**. Cliquez sur **Ajouter un compte**, confirmez, connectez-vous dans la nouvelle fenêtre Claude et ouvrez **Code**.
2. Après la première connexion, quittez Claude avec `⌘Q`, sélectionnez ce compte et cliquez à nouveau sur **Changer** pour charger la liste partagée.
3. Ensuite, sélectionnez un compte et cliquez sur **Changer**. Claude se ferme normalement, l’index local est synchronisé automatiquement et le compte choisi s’ouvre. Terminez ou enregistrez le travail en cours avant de changer.

Ajoutez d’autres comptes de la même façon. Une connexion expirée peut nécessiter une nouvelle authentification.

## Fonctionnement et limites

- Chaque compte utilise son propre dossier Claude. Claude gère la connexion ; l’outil n’exporte ni ne copie les identifiants. Il n’utilise aucun proxy et ne change pas de compte en fonction du quota.
- Les transcriptions Code locales partagent `~/.claude/projects`. Une tâche en arrière-plan et le changement de compte synchronisent les index de la barre latérale. Claude peut devoir redémarrer pour relire la liste.
- Les conversations cloud, Cowork, les quotas, les connecteurs propres aux comptes et les réglages propres à Desktop restent séparés.
- Les sessions SSH, WSL, les worktrees personnalisés et autres sessions spéciales ou non reconnues peuvent être ignorés. Les espaces temporaires conservent leur chemin d’origine ; supprimer leur dossier de profil peut empêcher leur ouverture. Si plusieurs dossiers d’organisation existent, la synchronisation s’arrête sans choisir au hasard.
- Les enregistrements en conflit ou invalides sont conservés et les index sont sauvegardés avant remplacement. Les suppressions ne sont pas propagées. Le format interne de Claude Desktop n’est pas documenté et peut changer après une mise à jour.

**Validation :** sur le Mac actuel, le compte B a affiché la barre latérale Code locale du compte A. La synchronisation de plusieurs comptes et les protections ont été testées avec des données simulées ; la reprise de conversations réelles et les autres versions de Claude ne sont pas encore entièrement validées.

## Désinstallation

Exécutez `./uninstall.sh`. Les profils Claude, conversations et sauvegardes locales sont conservés.

## Licence

[MIT](../LICENSE). Ce projet indépendant n’est ni affilié ni approuvé par Anthropic.
