[English](../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · Español · [Français](README.fr.md) · [Deutsch](README.de.md)

# Cambio de cuenta de Claude

Una aplicación no oficial y sencilla para macOS que permite cambiar entre cuentas de Claude Desktop y conservar visible la lista local de sesiones de Code. Cada cuenta inicia sesión por separado y solo se usa una ventana de Claude a la vez.

## Instalación

Necesitas macOS, Claude Desktop en `/Applications`, Xcode Command Line Tools y `/usr/bin/python3` 3.9 o posterior.

```sh
git clone https://github.com/gjw199513/claude-account-switcher.git
cd claude-account-switcher
./install.sh
```

Abre **Claude Account Switcher** desde `~/Applications`. La interfaz sigue el idioma del sistema: inglés, chino simplificado, japonés, coreano, español, francés o alemán.

## Uso

1. El perfil actual es la **cuenta A**. Pulsa **Añadir cuenta**, confirma el cambio, inicia sesión en la nueva ventana de Claude y abre **Code**.
2. Tras el primer inicio de sesión, cierra Claude con `⌘Q`; selecciona esa cuenta y pulsa **Cambiar** otra vez para cargar la lista compartida.
3. Después, selecciona una cuenta y pulsa **Cambiar**. Claude se cierra normalmente, el índice local se concilia de forma automática y se abre la cuenta elegida. Termina o guarda el trabajo activo antes de cambiar.

Añade más cuentas del mismo modo. Si una sesión caduca, puede ser necesario volver a iniciar sesión.

## Funcionamiento y límites

- Cada cuenta utiliza una carpeta de datos independiente. Claude gestiona el inicio de sesión; la herramienta no exporta ni copia las credenciales. No usa un proxy ni cambia de cuenta según la cuota.
- Las transcripciones locales de Code comparten `~/.claude/projects`. Una tarea en segundo plano y el cambio de cuenta concilian los índices de la barra lateral. Claude puede necesitar un reinicio para volver a leer la lista.
- Los chats en la nube, Cowork, las cuotas, los conectores de cada cuenta y los ajustes propios de Desktop permanecen separados.
- Las sesiones SSH, WSL, worktrees personalizados u otras sesiones especiales o desconocidas pueden omitirse. Los espacios temporales conservan su ruta original; eliminar la carpeta de su perfil puede impedir abrir esas sesiones. Si hay varias carpetas de organización, la sincronización se detiene sin adivinar.
- Los registros conflictivos o inválidos se conservan y los índices se respaldan antes de sobrescribirlos. Las eliminaciones no se propagan. El formato interno de Claude Desktop no está documentado y puede cambiar con una actualización.

**Validación:** en el Mac actual se confirmó que la cuenta B muestra la barra lateral local de Code de A. La conciliación de múltiples cuentas y las protecciones se probaron con datos simulados; la continuación de conversaciones reales y otras versiones de Claude no se han validado por completo.

## Desinstalación

Ejecuta `./uninstall.sh`. Se conservan los perfiles, conversaciones y copias de seguridad locales de Claude.

## Licencia

[MIT](../LICENSE). Este proyecto es independiente y no está afiliado ni respaldado por Anthropic.
