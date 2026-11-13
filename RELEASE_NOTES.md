# Tidy 0.2.0

Two new cleaners and a Speed up page, explained like everything else in Tidy.

## Leftovers
Finds what uninstalled programs left behind:
- **Leftover folders** in Program Files, ProgramData and AppData that no installed program matches, nothing running
  uses, and that haven't changed for at least 3 months. Each one says why it looks left over. They are always
  "Your choice", because no cleaner can be completely sure.
- **Empty folders** left by removed programs.
- **Broken shortcuts** in the Start menu and on the desktop that point at programs that are gone (shortcuts to a USB
  drive that isn't plugged in are left alone).
- Right before deleting, Tidy checks every leftover again: if a program was installed or started using it
  meanwhile, it is skipped.

## Memory
- See how full your memory (RAM) is, and which apps use the most, each labelled **Safe to close**, **Your choice**
  or **Keep** (Windows' own processes, drivers and services can't be ticked).
- **Close ticked apps**: each app is asked to close normally, so it can ask you to save. Apps that stay open can be
  force-closed only if you say so.
- **Free up memory**: asks apps to hand back memory they aren't using (nothing closes, nothing is lost).
- **Clear standby cache** (administrator): drops files Windows kept in memory just in case.

## Speed up
Changes that really help games and everyday use, nothing risky, and every one can be undone in Tidy.
- **Game Boost**: one click before you play sets best-performance power, closes the background apps you tick and
  hands back unused memory. Stopping it puts your power setting back.
- **Checkup** with one-click fixes: Game Mode, Xbox background recording (costs FPS), power mode, mouse
  acceleration (for consistent aim), graphics driver age with links to NVIDIA / AMD / Intel, days since the last
  restart, free space on the Windows drive, and transparency/animations on low-end PCs.
- **Startup apps**: turn off apps that open with Windows, with the same switch Task Manager uses. Each is explained;
  drivers, antivirus and anti-cheat (Vanguard, FACEIT) are kept on.
- **Graphics card for games** (laptops with two graphics chips): finds Steam, Epic and Riot games (VALORANT, League)
  and sets them to the fast graphics card, keeping any other Windows graphics options for that game.
- **What Tidy won't do, and why**: service disabling, registry cleaning, "ping boosters", turning off Defender or the
  page file, always-on RAM boosters, overclocking.

## Updates
- **Tidy now updates itself.** A few seconds after it starts it looks for a new version on GitHub and shows a banner
  with **Update now**. The installer is checked before it runs, installs quietly, and Tidy opens again by itself.
  Settings > Updates has **Check for updates** and a switch to turn the automatic check off.
- Coming from 0.1.0 (which had no updater): install this version once by hand; later ones arrive by themselves.

## Also
- The Overview's "Worth a look" card now counts leftovers too.
