[English](../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · Français · [Deutsch](README.de.md)

# Changement de compte Claude

Une petite application macOS non officielle pour changer de compte Claude Desktop tout en conservant la liste locale des sessions Code. Chaque compte est connecté séparément et une seule fenêtre Claude est utilisée à la fois.

**Validation de l’utilisation :** les données chiffrées et réponses simulées ont été testées. L’accès au trousseau et la lecture en ligne avec des comptes réels restent à vérifier.

## Installation

Il faut macOS, Claude Desktop dans `/Applications`, Xcode Command Line Tools et `/usr/bin/python3` 3.9 ou plus récent.

```sh
git clone https://github.com/gjw199513/claude-account-switcher.git
cd claude-account-switcher
./install.sh
```

Ouvrez **Claude Account Switcher** depuis `~/Applications`. L’interface suit la langue du système : anglais, chinois simplifié, japonais, coréen, espagnol, français ou allemand.

Le menu en haut à droite permet de choisir une langue ou de suivre celle du système. Pour consulter l’utilisation, sélectionnez le compte et cliquez sur **Actualiser**. Le premier accès est expliqué et macOS peut demander l’accès à Claude Safe Storage dans le trousseau. La connexion Claude Desktop existante est utilisée, sans nouvelle connexion ni message au modèle. Le jeton est déchiffré brièvement en mémoire et envoyé uniquement à `api.anthropic.com` en HTTPS ; il n’est ni enregistré ni renouvelé. Après la première lecture réussie, la consultation revient environ toutes les 15 minutes pendant la session macOS ; l’actualisation manuelle attend cinq minutes. Les lectures de plus de 30 minutes ou après réinitialisation sont masquées. La connexion d’un compte inactif peut expirer jusqu’à son ouverture dans Claude. Le format et l’API ne sont pas publics et peuvent changer ou limiter les requêtes.

## Utilisation

1. Le profil Claude actuel est le **compte A**. Cliquez sur **Ajouter un compte**, confirmez, connectez-vous dans la nouvelle fenêtre Claude et ouvrez **Code**.
2. Après la première connexion, quittez Claude avec `⌘Q`, sélectionnez ce compte et cliquez à nouveau sur **Changer** pour charger la liste partagée.
3. Ensuite, sélectionnez un compte et cliquez sur **Changer**. Claude se ferme normalement, l’index local est synchronisé automatiquement et le compte choisi s’ouvre. Terminez ou enregistrez le travail en cours avant de changer.

Ajoutez d’autres comptes de la même façon. Une connexion expirée peut nécessiter une nouvelle authentification.

## Fonctionnement et limites

- Chaque compte utilise son propre dossier Claude. Le changement ne déplace ni ne remplace les identifiants ; la consultation utilise le jeton Desktop comme indiqué ci-dessus. Aucun changement automatique selon le quota.
- Les transcriptions Code locales partagent `~/.claude/projects`. Une tâche en arrière-plan et le changement de compte synchronisent les index de la barre latérale. Claude peut devoir redémarrer pour relire la liste.
- Les conversations cloud, Cowork, les quotas, les connecteurs propres aux comptes et les réglages propres à Desktop restent séparés.
- Les sessions SSH, WSL, les worktrees personnalisés et autres sessions spéciales ou non reconnues peuvent être ignorés. Les espaces temporaires conservent leur chemin d’origine ; supprimer leur dossier de profil peut empêcher leur ouverture. Si plusieurs dossiers d’organisation existent, la synchronisation s’arrête sans choisir au hasard.
- Les enregistrements en conflit ou invalides sont conservés et les index sont sauvegardés avant remplacement. Les suppressions ne sont pas propagées. Le format interne de Claude Desktop n’est pas documenté et peut changer après une mise à jour.

**Validation :** sur le Mac actuel, le compte B a affiché la barre latérale Code locale du compte A. La synchronisation de plusieurs comptes et les protections ont été testées avec des données simulées ; la reprise de conversations réelles et les autres versions de Claude ne sont pas encore entièrement validées.

## Facultatif : préparation locale planifiée

Installez [Claude Code CLI](https://code.claude.com/docs/en/setup) 2.1.268 ou plus récent. Sélectionnez un compte, ouvrez les réglages de préparation, connectez-vous au CLI officiel, actualisez et confirmez l’adresse affichée avant d’activer l’horaire. Chaque compte possède sa configuration CLI isolée ; l’application ne lit pas les identifiants.

Tant que la session macOS est ouverte, une tâche en arrière-plan envoie une courte requête Haiku, même si la fenêtre est fermée. Si le Mac était éteint ou en veille, l’application demande confirmation avant le rattrapage lorsqu’elle est ouverte plus tard le même jour. Aucun nouvel essai automatique n’a lieu ce jour-là en cas d’échec. La requête consomme du quota et peut entraîner des frais ; une nouvelle fenêtre de cinq heures n’est pas garantie.

## Désinstallation

Exécutez `./uninstall.sh`. Les profils Claude, conversations et sauvegardes locales sont conservés.

## Licence

[MIT](../LICENSE). Ce projet indépendant n’est ni affilié ni approuvé par Anthropic.
