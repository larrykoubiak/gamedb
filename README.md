# GameDB

GameDB turns a retained RomVault export into a browsable, preference-ranked game
catalog. The code is split into three applications with distinct ownership:

| Package | Owns | Command |
| --- | --- | --- |
| `gamedb.derive` | `ref` and `derived`: source interpretation and stable inventory | `python -m gamedb derive` |
| `gamedb.catalog` | `catalog`: consumer projection, identity, scores and media | `python -m gamedb rebuild` |
| `gamedb.explorer` | Read-only HTTP pages and queries | `python -m gamedb serve` |

The data flow is deliberately one-way:

```text
RomVault + reviewed integrated packages + recovered history + reference
                  │
                  ▼
       Python derivation pass
       ref + derived
       DATs, systems, packages, paths, files,
       titles, raw tags, typed assertions, media
                  │
                  ▼
       SQL consumer projection
       catalog systems, titles, releases, facts,
       software identity, cached ranking and selected media
                  │
                  ▼
             explorer
```

The two executable manifests tell that story in detail:

- [`derive.yml`](derive.yml) declares the Python extraction layers.
- [`pipeline.yml`](pipeline.yml) declares the downstream SQL projection layers.

## Running only what changed

A full derivation is destructive and must be explicit:

```sh
python -m gamedb derive --plan
python -m gamedb derive --rebuild
```

Routine changes select their actual boundary. They do not silently replay
staging, path resolution, or name parsing:

```sh
# A path mapping changed
python -m gamedb derive --layers paths

# Parser/classifier rules changed; stable inventory is reused
python -m gamedb derive --from-layer names

# A user preference changed; refresh scoring and preference-aware media
python -m gamedb rebuild --from-layer scoring
```

After a full derivation, build the complete consumer projection with
`python -m gamedb rebuild`. Use `--plan`, `--layers`, `--from-layer`, or
`--through-layer` to inspect or select its SQL layers.

## US PlayStation retail catalog

The Game-Rave US checklist sets the scope for retail games and licensed
compilations. GameDB links those titles to local, SHA-1-verified US Redump
discs and shows their pressings, printed serials, and controller details.
The reviewed matches document title variations and retail boxes whose discs
have separate Redump entries. [Game-Rave checklist](https://game-rave.com/?page_id=105) · [Reviewed matches](reference/playstation_retail.json)

```sh
python -m gamedb seed-playstation --report data/logs/playstation-retail/matches.json --publish
python -m gamedb sync-playstation-manuals --catalog data/logs/playstation-retail/matches.json \
  --root /mnt/synology/photo/Manuals/PlayStation
docker compose exec -T explorer nice -n 10 python -m gamedb.explorer warm-manual-cache playstation
```

Open **PlayStation (US) retail catalog** in Explorer or go to
`/catalog/playstation`. The catalog uses Libretro and LaunchBox artwork,
scans of original booklets, and soundtrack sets from the configured VGM
library. [Kirkland’s Manual Labor](https://www.videogamemanual.com/ps1/index.html) · [Sony PlayStation Manuals archive](https://archive.org/details/SonyPlaystationManuals)

Omit `--publish` for a read-only audit. Pass `--sources` to reuse saved
reference indexes from a different directory. The default cache is
`data/media/cache/playstation-retail`.

Both Compose configurations mount the manual library read-only. Set
`GAMEDB_PLAYSTATION_MANUAL_HOST_ROOT` to use a different host directory or
`GAMEDB_PLAYSTATION_MANUAL_ROOT` when running Explorer directly.

## Mega Drive retail catalog

The Mega Drive catalog uses a pinned licensed game list and reviewed
cartridge compilations. It keeps the titles and dates shown for
Japan, North America, PAL, Brazil, South Korea, and Asia. Release notes on Sega
Channel and Meganet identify games and editions that were available only on
those services. The snapshot attributes the adapted release data to Wikipedia
contributors under CC BY-SA 4.0. [Pinned release list](https://en.wikipedia.org/wiki/Special:PermanentLink/1386009379#Licensed_games)

```sh
python -m gamedb seed-megadrive --report data/logs/megadrive-retail/matches.json --publish
python -m gamedb sync-megadrive-manuals --catalog data/logs/megadrive-retail/matches.json \
  --root "/mnt/synology/photo/Manuals/Mega Drive"
```

Open **Mega Drive retail catalog** in Explorer or go to `/catalog/megadrive`.
The seed matches region and verified No-Intro content, using MAME cartridge
hashes and the reviewed aliases in `reference/megadrive_retail_aliases.csv`.
`reference/megadrive_retail.json` records reviewed compilations and exact
archive exceptions for original retail cartridges, including some independently
published releases. The report measures release and asset coverage by market.
Omit `--publish` to generate a report in a read-only database transaction.

The regional pages show LaunchBox descriptions and artwork, Libretro images
and ROM header codes, MAME cartridge details, Sega Retro scans, Digital Press
manuals, and matched VGM soundtracks. Source indexes are cached under
`data/media/cache/megadrive-retail`. Use `--sources` to choose a cache directory
or `--html` to use a saved copy of the pinned release list. The manual sync
checks source hashes where supplied and publishes local PDFs to the shared
manual viewer. The two Compose configurations mount the library read-only.
Set `GAMEDB_MEGADRIVE_MANUAL_HOST_ROOT` for a different host directory or
`GAMEDB_MEGADRIVE_MANUAL_ROOT` when running Explorer directly.

Warm cover and page previews after syncing the library. Run the warmer in
Explorer so it uses the same manual mount and cache paths as the reader.

```sh
docker compose exec -T explorer nice -n 10 python -m gamedb.explorer warm-manual-cache megadrive
```

The command reuses existing previews and reports any unreadable manuals. Use
`snes` to warm the SNES library or `--workers` to adjust concurrency.

Import the Genesis translations from the local ROMhacking.net backup after
publishing the catalog.

```sh
python -m gamedb sync-megadrive-translations \
  --source /mnt/synology/backup2/romhacking.net-20240801/translations/genesis \
  --report data/logs/megadrive-retail/translations.json
```

Explorer shows patches under the matching regional release. **Has translation**
filters the catalog, and **Download ROM** builds a translated `.md` from the
verified cartridge using the GameDB API key. The [reviewed packages](reference/megadrive_translation_reviews.json)
record the exact IPS members and base ROMs for packages that needed individual
verification. The audit lists projects that could not be matched. The patch
library lives in `data/media/megadrive-translations` and both Compose
configurations mount it read-only. Set `GAMEDB_MEGADRIVE_TRANSLATION_ROOT` when
running Explorer directly with a library created using `--root`. Some older
patch archives require `7z` to extract their members.

## NES and Famicom retail catalog

The catalog covers licensed Japanese, North American, and PAL cartridges,
official multicarts, Bandai Datach, and reviewed original-era North American
independent releases. It adapts the release tables under CC BY-SA 4.0. The seed
matches verified No-Intro archives by title and region, with MAME program and
graphics chip hashes for reviewed variants. [Pinned release tables](https://en.wikipedia.org/wiki/Special:PermanentLink/1385181858#Licensed_games) · [MAME cartridge records](https://github.com/mamedev/mame/blob/mame0285/hash/nes.xml)

```sh
python -m gamedb seed-nes --report data/logs/nes-retail/matches.json --publish
python -m gamedb sync-nes-manuals --catalog data/logs/nes-retail/matches.json \
  --root /mnt/synology/photo/Manuals/NES
python -m gamedb sync-nes-translations \
  --source /mnt/synology/backup2/romhacking.net-20240801/translations/nes \
  --report data/logs/nes-retail/translations.json
```

Open **NES / Famicom retail catalog** in Explorer or go to `/catalog/nes`.
The catalog shows regional LaunchBox and Libretro artwork, MAME board and
cartridge codes, and local NSF and NSFE soundtrack sets. The seed uses the
Rx2.0 Calibre metadata to identify region and language and links PDFs by their
source SHA-1. Source indexes are cached in `data/media/cache/nes-retail`.
Omit `--publish` for a read-only audit. [Rx2.0 Manual Restoration Project](https://www.gamingalexandria.com/wp/2025/04/rx2-0-ressurectionxtras-nes-famicom-manual-restoration-project-complete/)

Both Compose configurations mount the manual and translation libraries
read-only. Set `GAMEDB_NES_MANUAL_HOST_ROOT` for another manual library on the
host or `GAMEDB_NES_MANUAL_ROOT` when running Explorer directly. Warm previews
in the Explorer service with `python -m gamedb.explorer warm-manual-cache nes`.

The importer attaches patches to the cartridge revision supported by checksum
evidence. **Download ROM** uses the GameDB API key and builds a `.nes` image
when the patch layout is verified. Reviewed IPS builds check their output
against pinned SHA-1 values. The translation report records projects that
could not be matched. [Reviewed patch packages](reference/nes_translation_reviews.json)

## SNES retail catalog

The first GameDB V2 catalog starts with a [pinned SNES retail release list](https://en.wikipedia.org/wiki/Special:PermanentLink/1384177751#Retail_releases).
It groups titles across Japan, North America, and PAL releases and keeps the
market titles, date precision, and documented editions. The JSON snapshot
records the source revision and attributes the adapted release data to
Wikipedia contributors under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

Generate a match report against an existing GameDB catalog.

```sh
python -m gamedb seed-snes --report data/logs/snes-retail/matches.json
```

`--html` accepts a saved HTML copy of the pinned revision. The matcher uses
No-Intro releases with complete content signatures, verified hashes, and a
resolved package path. Title and market evidence link the base archives.
Conflicting claims remain reviewable. The retail projection excludes flagged
prototypes, demos, unlicensed titles, modified dumps, and later distribution
variants from base matching. Unclassified tags need a reviewed content signature
and archive label before they qualify. Documented Nintendo Power and SuFami Turbo
editions have their own match scopes.

Publish the snapshot to `app.snes_retail_catalog` and open **SNES retail catalog**
in Explorer, or go directly to `/catalog/snes`.

```sh
python -m gamedb seed-snes --publish
# With the catalog-builder image
docker compose run --rm catalog-builder python -m gamedb.catalog seed-snes --sources /data/media/cache/snes-retail --publish
```

The report command uses a read-only database transaction. Run the publish
command again after a catalog refresh to update the matches and Almanac links.
The report shows title coverage and regional release coverage.
Reviewed matches cite evidence from the [MAME cartridge list](https://github.com/mamedev/mame/blob/mame0285/hash/snes.xml),
the [MAME SuFami Turbo list](https://github.com/mamedev/mame/blob/mame0285/hash/snes_strom.xml),
and locally imported LaunchBox and Libretro metadata.
[`reference/snes_retail_aliases.csv`](reference/snes_retail_aliases.csv) records regional spellings and alternate titles.
[`reference/snes_retail.json`](reference/snes_retail.json) records edition groupings,
reviewed content signatures, and notes for disputed regional releases.

The same command enriches game and release pages. LaunchBox supplies descriptions.
The regional pages show release dates, publisher and developer credits, product
codes, documented boards, box art, title screens, and manual links where evidence
is available. The artwork viewer also includes gameplay screenshots and clear
logos. The report measures the coverage of each field by market.

The selected release shows genre and player count from the archive's preferred
metadata. Controller icons also show peripherals whose headerless CRC32 matches
a verified base ROM. [OpenEmu SNES input data](https://github.com/OpenEmu/SNES9x-Core/blob/6b1495d48bdef85e04cb96f5050601b9c6be3d88/SNESGameCore.mm)

The regional pages also play SPC sets from the published VGM inventory when
Explorer has a `GAMEDB_VGM_ROOT`. The catalog matches sets to verified editions
and uses named regions and revisions when the rip specifies them. Rerun
`seed-snes --publish` after a VGM import to refresh the links and coverage.

Source indexes are cached in `data/media/cache/snes-retail`. Use `--sources` to
reuse a saved directory. Saved SNES Central scan lists and board pages supply
physical cartridge evidence alongside the catalog's Libretro and MAME records.
`--hash-cartridges` verifies local No-Intro ZIP members against their catalog
SHA-1 and caches SHA-256 fingerprints for ares PCB matches. Later runs reuse
the fingerprints. [SNES Central scans](https://snescentral.com/scan_index.php) · [ares database](https://github.com/ares-emulator/ares/blob/v148/mia/Database/Super%20Famicom.bml)

Manual links retain their market and source. Peebs’ archive and the Kirkland
set cover North America and PAL, and Peebs’ Super Famicom list, Gaming Alexandria
and Nintendo supply Japanese scans. [Peebs](https://sites.google.com/view/snesmanuals) · [Super Famicom manuals](https://sites.google.com/view/superfamicommanuals) · [Gaming Alexandria](https://www.gamingalexandria.com/wp/scans/super-famicom/)

Mirror the manuals from a saved SNES match report into the NAS library.

```sh
python -m gamedb sync-snes-manuals --catalog data/logs/snes-retail/matches.json \
  --root /mnt/synology/photo/Manuals/SNES
```

The command keeps PDFs by market, verifies published checksums where available,
and reuses files from earlier runs. Reviewed replacement sources and page
orders for image scans are in
[`reference/snes_retail_manual_files.json`](reference/snes_retail_manual_files.json).
Explorer shows the selected release's manual cover and opens its local PDF in
a book viewer. The reader and cover previews use Poppler, which is installed in
the Explorer image. Both Compose configurations mount the NAS folder
read-only at `/mnt/snes-manuals`. Set
`GAMEDB_SNES_MANUAL_HOST_ROOT` for a different Compose host path. Set
`GAMEDB_SNES_MANUAL_ROOT` to the library directory when running Explorer directly.

Import translations from a local ROMhacking.net backup after publishing the
SNES catalog.

```sh
python -m gamedb sync-snes-translations \
  --source /mnt/synology/backup2/romhacking.net-20240801
```

The importer checks the source CRC32 and size embedded in each BPS or UPS file
against a verified retail ROM. For a package containing one IPS file, it uses
the unambiguous base checksums recorded in the backup and records any copier
header or interleaving requirement. Explorer lists the downloads under the
matching release in a Translations table with authors, versions, and release
dates. English patches appear first.

Each entry in the release detail API carries the base release signature, the
base ROM SHA-1, the patch SHA-256, and the required input layout.
The [author reference](reference/translation_authors.json) resolves the
backup's contributor IDs through the NeoROMhacking community directory and
includes saved ROMhacking.net project credits for matching versions and dates.

**Download ROM** generates a translated `.sfc` from the exact verified base at
request time. It handles IPS patches with or without a copier header and
headerless BPS and UPS patches. The archive retains the original ROM and
patch files. Explorer reads the originals through `GAMEDB_ROM_ROOT`.
Interleaved patches remain available as patch downloads.

Launcher clients can read `romDownloadUrl` on supported entries and request it
with the existing GameDB API key in the `Authorization: Bearer` header. The
browser uses the same authenticated route.

```text
GET /api/v1/releases/{baseReleaseSignature}/translations/{key}/download
```

The command stores patch files and their release links in
`data/media/snes-translations`, which both Compose configurations mount
read-only. Some older ZIPs require `7z` for Deflate64 extraction. Use `--root`
to write to another directory and set
`GAMEDB_SNES_TRANSLATION_ROOT` when running Explorer directly from that library.

## Integrated releases

Reviewed ZIP packages that are intentionally outside RomVault can be imported
without adding rows to `staging.rv_files`. The maintained manifest supplies the
catalog title and system while every ZIP member is CRC-checked and SHA-1 hashed:

```sh
python -m gamedb import-integrated /mnt/synology/backup/games/Undub
python -m gamedb derive --rebuild
python -m gamedb rebuild
```

The Undub collection is described by
[`reference/integrated_releases.csv`](reference/integrated_releases.csv). All
of its releases use the `undub` modification tag, including packs whose source
filename describes a narrower audio, video, or edit fix.

## eXo staging

On `larry-tower`, inventory the read-only eXo library with the deriver image.

```sh
docker compose run --rm --no-deps -v /mnt/exo:/mnt/exo:ro deriver \
  python -m gamedb import-exo /mnt/exo --dry-run
```

Omit `--dry-run` to publish the complete inventory in a single transaction.
An identical revision reuses its snapshot. Source changes create a new
snapshot. The importer reads game ZIP names, media pack directories and
original artwork checksums. The game packages and media stay on the share.

The `staging.exo_document` and `exo_record` tables retain the XML lists,
playlist rules, aliases and runtime indexes. A primary game record belongs to
one platform and one local game ID. `exo_asset` identifies each relative
library path. `exo_location` preserves its loose, packed and URL locations,
including original ZIP member names, positions and available CRCs.

`exo_asset_link` records how a game owns a manual, extra, launch file or
image. Multiple games can display the same artwork. The importer follows
explicit XML paths, per-game folders, media pack membership, eXoGUI's
per-platform primary-title and title-plus-ID lookup, and LaunchBox's local
image and thumbnail IDs. `exo_image_evidence` retains matching rows from the
bundled LaunchBox image databases. A shared public database ID cannot extend
an existing local artwork association to another game. Conflicting copies,
ambiguous associations and missing source references are recorded in
`exo_issue`. Coverage counts are stored in `exo_snapshot.counts`.

## Browsing eXo

After staging a new snapshot, publish its editions and attachments on `larry-tower`.
The catalog builder and Explorer both read the library at `/mnt/exo`.

```sh
docker compose run --rm --no-deps catalog-builder python -m gamedb.catalog rebuild --layers exo
```

The MS-DOS, Windows 9x and ScummVM collections appear under **eXo** in the Explorer and in
**Computers** in the TV launcher. An edition can appear under its original hardware and in multiple
collections. ScummVM editions retain their game directory, original platform hint, engine/game ID
and bundled runtime version. An unmapped platform stays discoverable through its collection.
The MS-DOS list includes eXoDOS PC booters and identified DOS editions from eXoScummVM.

The IBM PC list groups verified DOS, Windows and ScummVM editions of a game under one title.
The builder checks names and documented aliases against credits, dates and source identifiers.
Reviewed matches use evidence such as identical game data from the selected edition inside a
bundle. Each edition keeps its own source credits, score and attachments. Earlier eXo detail
links open the grouped game.

A source entry keeps its original LaunchBox fields and regional alternate titles. System snapshots
carry genre, developer, publisher, series and player count through `softwareFacts`. For a row with a
`sourceDetailKey`, `GET /api/v1/exo/{sourceDetailKey}` returns the entries, edition choices and assets.
The entries include full descriptions, dates, ratings, play modes and all remaining source fields.
The public Explorer uses `/api/exo/{sourceDetailKey}` and opens an eXo entry at
`/software/exo/{sourceDetailKey}`. Earlier `/?exo={sourceDetailKey}` bookmarks redirect there.

Manuals, maps, books, music, videos, artwork and collection guides have public
`/related-media/{assetKey}` links. Files stay on the share, including items inside companion ZIPs.
Shared supplements verified by SHA-256 can appear once with multiple credited owners. The TV
launcher shows title details and offers browser links and QR codes for these items.

The default scoring profile adds 75 points for eXo and another 75 for an edition identified as
**IBM / PC Compatibles**. The hardware evidence determines the PC bonus, including for games
packaged with ScummVM. Edit the two weights in `app.user_preference` and rebuild the `scoring` layer
to refresh the rankings. Other applicable
preferences, including gameplay hack penalties, still contribute to each edition's score.
The catalog caches the winner per user, platform or collection, and hack-filter setting.

When eXo wins, `preferredEditionKey` identifies the selected source edition and the catalog uses
its artwork and metadata. An exact score tie favors the existing DAT release. For a matched
installable release, `preferredReleaseSignature`, `installSourceCollection`, `installReleaseTitle`
and `installScore` identify what the launcher can install. Entries available only through eXo
support browsing and media.

## Video game soundtracks

GameDB inventories the music share in place, retaining each source collection,
track, archive and supported companion file. Extracted sets and same-named
archive copies within a collection share a soundtrack entry. ZIPs can supply a
track list when there is no extracted copy. The importer also lists individual
members of UnExoticA LHA and JoshW 7-Zip packages. It preserves Amiga module
names such as `MOD.Title` and keeps sample banks in the same album. The original
packages are available as downloads. SPC ID666 labels, NSF, SID and GBS credits
and subsong counts, and PSF track names and credits appear when available.
NES subsong titles come from NSFe or NSF2 metadata and bundled NSF playlists.

Run a read-only match against the configured catalog before publishing.

```sh
python -m gamedb import-vgm \
  --root "/mnt/synology/music/VGM/By Format" --report /tmp/gamedb-vgm.jsonl
```

The report records source paths, accepted evidence and candidates for ambiguous
matches. SNES matching starts with the full archive or directory name. The
bracketed SNESMusic code and embedded SPC track labels are kept for provenance
and display. PlayStation sets also use consistent PSF game tags when they
preserve the full title and edition in the filename. Both platforms can use
same-platform LaunchBox aliases already associated with the catalog. The
[reviewed title file](reference/vgm_titles.csv) records verified spelling,
regional titles and edition conflicts.

For C64, the SID title must agree with the filename. Composer-folder links
also require the SID year and publisher to agree with a release in GameDB.
The HVSC game folder can corroborate a unique title when the release credits
are missing. Conflicts and remaining mixed collections stay in the inventory
for review. A catalog identity change may require another import to refresh
the matches.

UnExoticA's accompanying game notes provide titles, alternate titles, and
edition evidence for Amiga, CD32 and CDTV. Atari ST matching uses long SNDH
filenames in composer and game folders. The import report retains uncertain
matches for review. Install system libarchive when running the importer or
Explorer directly. Both Compose images include it.

Refresh the cartridge and handheld sets from the HCS64 index with
`python -m gamedb.vgm.fetch_joshw --root "/mnt/synology/music/VGM/By Format"`.
Add `--download` to save the packages under `JoshW/` in that library. Use
`--bucket` to refresh a single index subdomain, such as `spc`. Packages with
the same size and index revision are reused. Downloads prefer a `[fixed]`
archive when both copies share a version. The VGM importer reads the full
package names and platform tags, then lists tracks and shared libraries from
the 7-Zip archives. Place individual JoshW Amiga or CD32 archives under
`JoshW/cdi/amiga/` with their source filenames. The importer can link regional
names when the catalog supports the same soundtrack version, and disc titles
when a rip's notes confirm the name and platform. Ambiguous titles stay in
the matching report.

Add `--publish` to atomically replace the VGM inventory. In Compose the catalog
builder sees the share at `/mnt/vgm`.

```sh
docker compose run --rm --no-deps --entrypoint python catalog-builder \
  -m gamedb.vgm --root /mnt/vgm --publish
```

Set `GAMEDB_VGM_ROOT=/mnt/vgm` for the Compose Explorer, or set it to the NAS
path when running Explorer directly. Matched games then show their music on the
**Soundtracks** tab in the Almanac. The player handles browser audio and
emulates SPC, SID, PSF, NSF, GBS, GSF, 2SF, NCSF, USF, HES, SNDH, VGM and common
Amiga tracker formats in the browser. ZXTune's bundled vgmstream decoder plays
GENH and PlayStation XA streams. The Soundtracks tab shows a playlist with a
shared player and a source selector for games with several sets. The tab
shows the soundtrack for the preferred release when it has a matching version
and prefers the fixed copy when JoshW publishes a correction. The player can
move between subtunes in GBS, NSF, SID and SNDH. SNDH subtunes appear when
the decoder opens the file. Tracks can load shared libraries from the same
soundtrack. Download links provide the original tracks and archives.
Downloads follow the Explorer's existing public related-media access model.

## Inspecting names

The parser can be exercised without changing the database:

```sh
python -m gamedb parse-name No-Intro 'Example (USA) (En,Fr).zip' --classify
```

See [the database model](docs/database.md), [archive-name rules](docs/archive_names.md),
[current status](docs/status.md), and [SQL index](sql/README.md).

## Explorer

The Explorer opens on **All platforms** in Tiles view. A title opens its
**Almanac** page. Tabs give access to the overview, artwork, releases, related
media and soundtracks. Each tab can be shared using its URL. Back to catalog
returns to the current search, filters and page. Native permalinks verify the
software identity key and use the numeric ID as a lookup hint.

Switch to **Table** to compare archives, scores and regions. Rows still expand
for a quick release comparison. The browser remembers the layout. Both views
search alternate release titles and keep the current filters and page when
you switch.
Platform icons identify systems in the sidebar and the table's Platform column.
The bundled artwork uses the mappings in `reference/system_icons.csv`.
Unmapped systems retain a neutral icon and their names. Artwork attribution is
available through the sidebar’s **Platform icon credits** link.
Click a cover or an image in the artwork gallery to enlarge the original in a
modal. Close it with Escape, the close button, or a click on the backdrop. Focus
returns to the image button and the current search stays in place.
Previous/next buttons and the left/right arrow keys cycle through the current
game's available artwork, wrapping at either end. A counter shows the position
when a game has multiple images.

The Explorer requests artwork near the visible results. Table previews fit
within 128 × 128 pixels and tile and gallery previews within 320 × 320. The
first request generates a WebP from the catalog's selected Libretro or LaunchBox
image. Subsequent requests reuse the file in `data/media/previews`, which both
Compose configurations mount at `/data/media/previews`. For a host process,
`GAMEDB_PREVIEW_CACHE` can override the cache directory. The cache survives
Explorer restarts and regenerates previews when source files change. Browsers
can reuse previews for an hour and revalidate them by ETag. The original
`/media/` URLs continue to serve full-resolution artwork to zoom and launchers.
Choosing a system narrows the current search; **All platforms** widens it again
without clearing the search text. Results remain paginated, and release details
and corrections stay attached to each result's actual system. The explorer's
`GET /api/titles?q=...&page=1&page_size=100` endpoint searches all platforms;
`GET /api/systems/{id}/titles` keeps the same payload scoped to a system.

Use the sidebar category selector to narrow the system tree to consoles,
handhelds, computers, arcade, or other devices. It combines with the tree's text
filter and leaves the current game search scope unchanged. Categories are explicit
values in `reference/canonical_systems.csv` and appear as `category` in the systems
API. See [system classification policies](docs/system_mapping.md) for hybrids and
the rebuild commands needed to publish category changes.

Searchable metadata filters sit beside the game search: genre, developer,
publisher, franchise, players, enhancement hardware, rumble, analog, origin, and
tags. Description is excluded. Select multiple values within a field to match any
of them; different fields must all match. Filters use the selected metadata shown
in game details, combine with title/alternate-title search, and persist through
paging and platform changes. Active chips remove individual values; **Clear
filters** resets metadata filters while keeping the title search.

Filter choices and software counts follow the current platform, title search,
and other fields; a field ignores its own selection so additional choices stay
available. Large lists show the first 100 matching values and support searching.
The title endpoints accept a `filters` query parameter containing a JSON object
such as `{"genre":["Action","Adventure"],"developer":["Nintendo"]}`.
`GET /api/metadata-options?key=genre` accepts the same `q` and `filters`, optional
`system_id`, and a `search` term for finding values.

**Hide ROM hacks** starts enabled in the Explorer and remembers your choice in
this browser. It hides releases tagged `hacked`, `modified` or `trained`.
Translations and undubs stay eligible even with one of those tags. Fixes and
copy-protection cracks alone also stay eligible. When the preferred release is
hidden, the catalog uses the highest-ranked eligible release. Games whose
releases are all hidden drop out of the results.

API clients can request this view with `hide_rom_hacks=1` on the system list,
title searches, metadata options, release details, and both versioned catalog
endpoints. Omitting the parameter returns the full catalog. Title and release
rows expose the boolean `isRomHack` alongside the source `dumpModifications`.
Release details include the alternatives and identify the selected release for
the requested view. Each versioned view has its own ETag. Both preferred
release signatures can be used with the install API.

The Explorer caches the system list, title pages, searches and metadata dropdowns
as they are opened. Requests share a result when the user, system, page, search
and filters match. Each request checks a small database revision that tracks
published scores, metadata, release facts, arcade plans and selected artwork.
The first request after a change loads fresh results. Concurrent requests for the
same result share the work. The cache holds up to 512 entries or 64 MiB, evicts
the least recently used entries and starts empty when the Explorer restarts.

The scoring build stores the preferred release and tie count for each user's
games in PostgreSQL. Even the first visit to a system uses those stored choices.
The metadata build publishes the listing revision. To upgrade an existing catalog
in place, run the following command once before starting the updated Explorer.

```sh
docker compose run --rm --no-deps --build --entrypoint psql catalog-builder \
  -X -v ON_ERROR_STOP=1 --single-transaction \
  -f sql/layers/metadata/095_listing_generation.sql \
  -f sql/layers/scoring/025_cache_preferred_releases.sql \
  -f sql/layers/scoring/027_rom_hack_filter.sql
```

There are two Compose entry points with deliberately different database
ownership:

- `compose.yaml` is the self-contained `larry-tower` deployment and owns
  PostgreSQL.
- `compose.dev.yaml` runs local code against the `PG*` connection in `.env` and
  never starts PostgreSQL.

For workstation development, add this to the local `.env` alongside the tower
connection and use ordinary Compose commands:

```env
COMPOSE_FILE=compose.dev.yaml
PGHOST=larry-tower
PGPORT=9876
GAMEDB_EXPLORER_PORT=8082
```

```sh
# Rebuild and run the local explorer against the tower database.
docker compose up --build -d

# Run one-shot tools against that same database.
docker compose run --build --rm deriver --from-layer names
docker compose run --build --rm catalog-builder rebuild --from-layer scoring
```

On `larry-tower`, where `COMPOSE_FILE` is not set, copy `.env.example` to `.env`,
retain the credentials that initialized the database, then start the deployment:

```sh
docker compose up --build -d explorer
```

PostgreSQL data is retained at `./data/pgdata`. Application containers connect
to `db:5432`; `PGHOST` and `PGPORT` remain useful for commands run directly on
the host. Set `GAMEDB_EXPLORER_PORT=8080` to change the explorer's host port and
`GAMEDB_POSTGRES_PORT` to change the optional host database port.
The Libretro checkout is expected at `./data/libretro-thumbnails`; the catalog
builder caches its Git path index in `./data/media/cache` and the explorer
serves only selected image files from that read-only checkout.

The deployment stack also exposes the independent tool targets:

```sh
docker compose --profile tools run --build --rm deriver \
  python -m gamedb.derive --plan
docker compose --profile tools run --build --rm catalog-builder \
  python -m gamedb.catalog rebuild --from-layer scoring
docker compose up --build explorer
```

The `tools` profile does not run derivation or catalog work automatically. It
only makes those one-shot services available when explicitly requested.

On `larry-tower`, deploy from `/srv/docker/gamedb` so the existing
`./data/pgdata` bind mount is reused. The Compose file accepts the tower's old
`POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` names as fallbacks, so
its current `.env` can be retained. To keep the existing Cloudflare tunnel and
remove the obsolete Django/ETL containers after the source tree is replaced:

```sh
docker compose --profile public up --build -d --remove-orphans
```

The explorer retains `web` as a network alias for compatibility with the
existing managed tunnel origin.

## Verification

```sh
python -m unittest discover -s tests -v
```

## Recovered identity sources

Historical GameDB databases and review artifacts can be snapshotted into
history-owned `staging.history_*` tables without affecting `staging.rv_files`:

```sh
python -m gamedb import-history \
  --python-gamedb /path/to/recovered/GameDB \
  --legacy-archive /path/to/20160605-GameDB_Backup.7z \
  --patch-workbook /path/to/patches.xlsx
```

`OLD_GAMEDB` supplies the read-only SQLAlchemy URL for the legacy relational
database. The import preserves source IDs, hashes, Parent/Clone relationships,
source trust ratings, external mappings, reviewed match scores, workbook rows,
and artifact checksums.
The `software` catalog layer interprets unambiguous historical SHA-1 matches as
recovered software identity and extends them through unambiguous Parent/Clone
groups. A unique source-backed identity cascades to the remaining releases in
its effective title; collisions stop the cascade and become review candidates.
Maybe-Intro `[n]` translations may also join an existing software identity when
their playable member filename retains one unambiguous original title and that
title has exactly one source-backed anchor. This is a conservative typed rule
rather than a fuzzy title match. Remaining releases are grouped by exact title.
Importing history alone never changes the consumer catalog. Rebuild with
`python -m gamedb rebuild --from-layer software`.

## LaunchBox metadata

Download and retain a source snapshot, then import it into staging:

```sh
mkdir -p data/launchbox
curl -fL --retry 2 https://gamesdb.launchbox-app.com/Metadata.zip \
  -o data/launchbox/Metadata.zip
python -m gamedb import-launchbox import data/launchbox/Metadata.zip
python -m gamedb import-launchbox report --output data/launchbox/report-001
```

The ZIP SHA-256 identifies the snapshot; importing identical bytes again is a
no-op. Game, alternate-name and platform records retain their source fields and
XML in `staging.launchbox_record`. Image references can be imported separately
with the commands below; emulator rows remain only in the retained ZIP.

The report uses explicit `reference/launchbox_platforms.csv` mappings and exact
normalized names, including source aliases and catalog member titles. It keeps
numbers, accents and edition qualifiers; there is no fuzzy matching. A candidate
is `unique` only when both the catalog software and LaunchBox game have a single
counterpart within that canonical system. Ambiguous candidates get a second pass
using existing release dates and publisher/developer facts. A literal primary
title needs a matching year or company; an alias needs both. Known conflicting
companies/years and tied evidence leave the candidate unresolved. Multiple
catalog entries may receive `resolved_shared` enrichment links to the same game
without merging their identities; other resolutions use `resolved_source`.
These are evidence-backed candidates, not manually verified identity links.

Each new output directory contains `summary.json` (coverage and missing-field
counts), `matches.csv` (all software, statuses, titles, candidate/selected IDs, corroborating facts and resolution rules), and
`matched_games.jsonl` (source fields and aliases for selected candidates). Reports
record the source and mapping checksums. Use `--revision ZIP_SHA256` to select an
older import and `--platform-map PATH` to test another map. Numeric software IDs
are build-local, so regenerate the report after rebuilding the catalog.

Import and report commands leave the catalog unchanged. To publish selected
matches alongside the RDB metadata:

```sh
python -m gamedb rebuild --layers metadata
```

The metadata layer recalculates matches against the current catalog and publishes
both providers atomically. It retains source claims, prefers LaunchBox (score 100) over RDB
(score 50) per metadata field, and gives LaunchBox claims zero matched content hashes. Evidence
includes the LaunchBox game ID, source row, matcher version, mapping checksum,
match method and corroborating facts. LaunchBox claims are never used to
corroborate their own future matches. Unresolved candidates stay excluded, and
software identities are not merged. Missing optional sources are supported.

Genres are multi-valued tags. The metadata rebuild splits LaunchBox semicolon
lists and RDB spaced-slash lists, then applies the explicit aliases in
[`reference/genre_aliases.csv`](reference/genre_aliases.csv). For example,
`Action; Role-Playing` becomes two tags, and `Role-playing (RPG)` shares the
canonical name `Role-Playing`. Distinct subgenres remain separate. Equivalent
claims use the same name across providers while retaining separate provenance;
the original strings remain in evidence `match_details.original_genres` and raw
staging records. Edit the alias file and rerun the metadata layer to revise the
vocabulary; no source reimport is needed.

The importer and reporter are included in the deriver image; mount the ZIP/report
directory when running them in a container. The metadata builder is included in
the catalog-builder and explorer images.

### LaunchBox artwork fallback

After metadata has been published, import the image references from the same ZIP
and fill missing artwork slots:

```sh
python -m gamedb import-launchbox images data/launchbox/Metadata.zip
python -m gamedb import-launchbox media
```

The image import is atomic and idempotent. `staging.launchbox_image` retains all
image references; only Box - Front, Screenshot - Gameplay, Screenshot - Game
Title and Clear Logo are selected. After Libretro selection, the media rebuild
fills empty `boxart`, `snap`, `title` and `logo` slots, preferring images from
the preferred release's region. It follows published LaunchBox metadata links
first. For games without one, a reviewed release signature can identify the
LaunchBox artwork record by platform, database ID and title. The API reports
these image associations as `launchbox_reviewed`. The reviewed links live in
[launchbox_artwork.csv](reference/launchbox_artwork.csv).

Images are fetched on demand from `https://images.launchbox-app.com/`, verified
against the source CRC32 when available, and cached under
`GAMEDB_LAUNCHBOX_IMAGE_CACHE` (default `/data/media/launchbox`). Both Compose
explorers mount a persistent writable `data/media/launchbox` directory. A failed
download leaves no cache entry and can be retried. Only selected image filenames
can be fetched through the server; there is no arbitrary remote-URL proxy.

Launcher snapshots retain the existing media shape: `media.<kind>.path` is used
under `/media/`, including `launchbox/<kind>/<filename>` paths. A `provider` field
identifies the source. Artwork changes contribute to the catalog revision/ETag;
clients should revalidate cached snapshots. The explorer image must be rebuilt
when introducing the LaunchBox route; no launcher-specific image downloader is
needed.

## Libretro database staging

Keep a pinned upstream checkout beside the thumbnail checkout:

```sh
git clone --depth 1 https://github.com/libretro/libretro-database.git \
  data/libretro-database
python -m gamedb import-rdb data/libretro-database
```

The import records the Git revision, compiled RDB checksums and every raw typed
entry in `staging.libretro_rdb_*`. Common identity fields are additionally
normalized for matching, but no metadata is promoted to releases or software
at import time. Running the same revision again is a no-op; use `--replace`
only to repair that exact snapshot.

After import, build the relational software projection with:

```sh
python -m gamedb rebuild --layers metadata
```

Only exact SHA-1s resolving to one current software identity are accepted.
`catalog.software_fact` retains every competing value with support counts and a
rank; `catalog.software_fact_evidence` traces it back to the RDB row and matched
content. Region, serial, date and ratings remain release-level staging claims
rather than being flattened onto software.

The explorer treats recovered and generated groupings as accepted catalog
facts and exposes **Correct…** when an exception is found. Working decisions
are stored durably in `app.software_correction`, keyed by canonical
system and the complete release-content signature, then applied by rebuilding
the software and scoring layers. An assignment follows a signed target release
to its current software; a separation creates a manual software identity.
Mutation is gated by `GAMEDB_ENABLE_CORRECTIONS`; the workstation
`compose.dev.yaml` enables it, while the public deployment remains read-only by
default.

### Consumer catalog snapshots

Appliance clients can cache the preferred-release projection without replaying
the explorer's paginated queries:

```text
GET /api/v1/catalog
GET /api/v1/systems/{systemKey}/software
```

Versioned API requests require `Authorization: Bearer <GAMEDB_API_KEY>`. Keep
the key in the deployment environment rather than source or launcher config.

The catalog manifest provides the current scoring generation and stable system
keys. A system snapshot returns every preferred software row for that system,
including the preferred release content signature, selected artwork, and a
`softwareFacts` array of ranked metadata candidates with source support. Both
routes provide an ETag and honor `If-None-Match` with `304 Not Modified`.
For launcher metadata, read `items[].softwareFacts` on the system snapshot.
LaunchBox contributes `description`, `developer`, `publisher`, `genre` and
`player_count` through the same structure as RDB facts:

```json
{"key": "genre", "preferredValues": ["Platform"],
 "values": [{"value": "Platform", "rank": 1, "sourceScore": 100,
  "selected": true, "sourceProvider": "launchbox", "matchedContentCount": 0}]}
```

This abbreviated example omits provenance fields. `values` are ordered by rank
(best first); LaunchBox claims rank ahead of RDB. Read each field's
`preferredValues` array for display: one selected value for ordinary fields,
or all genre tags from the preferred available provider. RDB supplies a field
when LaunchBox has no nonblank matched claim for it. Each entry in `values`
includes `sourceScore` (LaunchBox 100, RDB 50) and `selected`; these scores are
source preferences, not confidence percentages. Within RDB, content support,
row support and then alphabetical order break ties. All source claims remain
available for provenance, including agreements and disagreements. The explorer
shows preferred values once, with evidence from any agreeing provider. Values are strings,
including player counts, and missing fields are absent (or `softwareFacts` is
empty). Identical values may appear from both providers; `candidateCount` counts
source claims, not distinct texts. Keep provenance if presenting alternatives.
`matches` includes the match method, LaunchBox `databaseId` and corroboration
`basis` when available. `sourceRevision` identifies the source snapshot.

The scoring generation, catalog listing revision and artwork signature contribute
to `catalogRevision`. The server caches up to 128 complete snapshot responses or
128 MiB in memory. A launcher with a current ETag can reuse its own copy even
after the server has evicted the snapshot or restarted. Revalidate with
`If-None-Match` when opening a system.

Numeric database IDs remain present for compatibility but are rebuild-local;
clients should persist the system key and release content signature instead.

After reviewing working corrections, promote them into the version-controlled
reference CSV and its `ref` materialization:

```sh
python -m gamedb promote-corrections
```

Promoted rows remain in `app` as audit history but no longer participate as
working decisions. Reviewed reference corrections take precedence on rebuild.

Maintained corrections live in `reference/software_overrides.csv`. An `assign`
row selects one release by system, source collection, archive name, and record
index and places it in a system-scoped manual `target_key`; an `exclude` row
prevents automatic identity inheritance for that release. Every selector must
resolve to exactly one current release or the software transaction stops.

Connection settings live in the ignored `.env`; exported shell values take
precedence.

## Arcade import and installation

MAME uses versioned machine definitions alongside RomVault storage inventory.
Import matching full `-listxml` output and an arcade-only classification DAT:

```sh
python -m gamedb import-arcade data/arcade/mame-0.285/XML/mame_724_0.285.xml \
  --arcade-dat 'data/arcade/mame-0.285/DATs/MAME 0.285 (arcade).dat' \
  --rom-dat-path 'DatRoot/Arcade/MAME/ROMs/MAME 0.285 ROMs (split).xml' \
  --chd-dat-path 'DatRoot/Arcade/MAME/CHDs/MAME 0.285 CHDs (merged).xml'
python -m gamedb derive --from-layer reference
python -m gamedb rebuild
```

The importer retains metadata and input SHA-256s in `staging.arcade_*`; replaying
identical inputs is a no-op. One active version per emulator is currently supported;
conflicting snapshots are rejected rather than mixing dependencies. Subsequent interpretation changes need only
`derive --layers arcade` and a catalog rebuild. Inputs under `data/arcade/` are
ignored by Git. Runtime containers need the retained database metadata, not the
original XML files. The deriver and explorer include the arcade module.

Arcade appears under `Various / Arcade`. MAME's explicit parent/clone families
form software identities; BIOS/device definitions remain support inventory.
Console/computer machines are excluded using the classification DAT. FBNeo uses
its arcade-only DAT and the same canonical Arcade system. FinalBurn Alpha is not imported.
Shared chips and split ZIP contents are excluded from automatic game identity
and Libretro metadata matching.

The authenticated `GET /api/v1/releases/{signature}/install-manifest` endpoint
returns schema version 2 for arcade. Its signature identifies the versioned
machine definition (`signatureKind=machine_definition`), not a complete ZIP
content signature. The software snapshot's `preferredReleaseSignature` and the
release listing's `installSignature` provide this value. Ordinary release
manifests remain schema version 1.

A complete arcade manifest includes a `bundleUrl`:
`GET /api/v1/releases/{signature}/install-bundle`. Extract the ZIP64 bundle into
an installation directory and launch `launchPath` with `preferredCore`.
`compatibleEmulators` records core filenames, DAT versions, input SHA-256s, and
`dat_validated` evidence. This validates requirements, not actual emulation.
The bundle contains `gamedb-install.json`, `roms/<machine>.zip`, any required
parent/BIOS/device ZIPs, and only the selected disks at
`roms/<machine>/<disk>.chd`. CHDs stay outside the ROM ZIPs. Fully inherited and
disk-only variants receive an empty launch ZIP while their content remains in
the dependency ZIPs. Bundles stream without recompressing CHDs or making a
multi-GB temporary copy; generated bundle downloads do not support resumption.

Completeness is separate from MAME's reported emulation status. Missing ROMs,
undumped requirements, samples, missing host files or changed ZIP member
size/CRC produce an incomplete manifest and block bundle downloads with HTTP
409. This first MAME implementation has no samples inventory importer, so
sample-dependent machines explicitly remain incomplete. Disk requirements use
RomVault's `alt_sha1_hex` content hash; `sha1_hex` remains the physical file hash.
Manifest checks validate file presence, CHD size and ZIP member size/CRC against
the inventory; they do not rehash large CHDs on every request or prove emulator
execution. Keep the target core compatible with the manifest's emulator definitions.

Import FBNeo after its ROM inventory has been exported to `rv_files`:

```sh
python -m gamedb import-arcade '/path/to/FinalBurn Neo v1.0.0.02 (ClrMame Pro XML).dat' \
  --emulator FBNeo \
  --rom-dat-path 'DatRoot/Arcade/FinalBurn Neo/roms/arcade/FinalBurn Neo v1.0.0.02 (ClrMame Pro XML).dat'
python -m gamedb derive --from-layer reference
python -m gamedb rebuild
```

FBNeo DAT CRC/size declarations resolve against version-scoped inventory. Cross-emulator
family links require equality of the complete game-ROM SHA-1/size sets, excluding
BIOS contents, and an unambiguous MAME family. Partial shared content never links
families. A single unchanged bundle is marked compatible with both only if it
satisfies both dependency graphs, hashes and member names with the same launch name.
Arcade ranks complete packages first, then non-preliminary emulation, then user
preference scores. The default FBNeo preference is +200; readiness does not distort
the visible score with huge negative penalties. MAME remains the fallback.

Both MAME and FBNeo thumbnail directories are searched. Neo Geo is retained as
`hardware=SNK Neo Geo`, independently of the canonical Arcade system and selected
core. AES/MVS mode selection is not inferred from shared ROM hashes; the launcher
currently retains the user's core BIOS settings. FBNeo Killer Instinct HDD sets
remain incomplete until their external HDD requirements are imported explicitly.

FBNeo sample DATs can be imported with `--samples-dat` and
`--samples-dat-path` alongside the ROM import. Samples resolve through `rv_files`
using the sample DAT CRC/size and retained inventory SHA-1. Bundles include
`system/fbneo/samples/<set>.zip`; `systemDirectory` tells the launcher to use that
private directory through a per-game RetroArch append config. To update an
existing catalog without rebuilding identities, add `--refresh-samples`, then
run `python -m gamedb.catalog rebuild --layers scoring`. MAME samples still
require a separate importer; FinalBurn Alpha inventory is not treated as FBNeo.
