# Public-safety rules

This repository will be published. Everything in it — files, commit messages, issues, pull
requests, review comments, and metadata inside data files — should be written as if it is
already public.

## Never record

- **Personal details of anyone involved:** real names beyond the GitHub handle, personal email
  addresses, phone numbers, home or work addresses, employers, clients, schools or other
  affiliations, travel plans, health or family matters.
- **Locations:** where a receiver, antenna or test bench is. Coordinates with more than two
  decimal places, street addresses, building names, or anything that narrows a location to less
  than a city. Tools take the receiver position as a command-line argument or a file outside
  the repository; examples use well-known public places or round numbers.
- **Machine details:** user names, host names, absolute paths from a personal machine
  (`/Users/<name>/…`, `/home/<name>/…`, `C:\Users\<name>\…`), serial numbers of instruments,
  MAC addresses, IP addresses, tokens and keys.
- **Private correspondence:** content of private messages or agreements with companies or
  people, even if they relate to the project.

## Data files

- SigMF metadata written by snappnt must not contain host names, user names, absolute paths or
  geolocation (`core:geolocation`) unless the user passes them explicitly for that recording. <!-- public-safety: ignore -->
- Recordings from real hardware are not committed (`out/` and `data/` are ignored). Before any
  recording is published, for example as a release asset, check its metadata for the items
  above.

## Automatic check

CI runs `python tools/check_public_safety.py`, which scans tracked text files for generic
patterns: email addresses outside an allow list, personal absolute paths, coordinate-like keys
with precise values, and a `core:geolocation` key. <!-- public-safety: ignore -->

It also reads the metadata of tracked JPEG, PNG, WebP and TIFF images (EXIF, XMP and PNG text
chunks) and reports GPS data, the date and time a photo was taken, and the camera make and
model. A metadata block it cannot parse is reported too. HEIC, HEIF and AVIF images are not
parsed and are always reported; convert them to JPEG or PNG first. The parser uses the Python
standard library only.

A list of specific private words (a family name, a street, a company) would itself publish
those words, so it is never committed. To check for such words locally, keep a list in a file
outside the repository, one term per line, and point the check at it:

```bash
SNAPPNT_PRIVATE_TERMS=~/.config/snappnt/private-terms.txt python tools/check_public_safety.py
```

This can be added as a local git pre-commit hook.

`CITATION.cff` names the maintainer on purpose, because a citation needs an author and the
maintainer chose to publish their name there. The maintainer's own private-terms list may
contain that name, so the two name lines in `CITATION.cff` carry the `public-safety: ignore`
marker, which lets the local check pass without removing the name from the list.

## Photos

A photo taken with a phone or camera usually carries EXIF metadata: often the GPS position
where it was taken, and the date, time and camera model. Strip it before committing the photo.
Either of these works:

- With [ExifTool](https://exiftool.org/), which removes all metadata in place:

  ```bash
  exiftool -all= photo.jpg
  ```

- With Python and Pillow only. Copying the pixels into a new image leaves every metadata block
  behind; `exif_transpose` first applies the EXIF orientation, so the photo stays upright once
  the orientation tag is gone:

  ```python
  from PIL import Image, ImageOps

  with Image.open("photo.jpg") as im:
      im = ImageOps.exif_transpose(im)
      clean = Image.new(im.mode, im.size)
      clean.paste(im)
      clean.save("photo-clean.jpg", quality=90)
  ```

Then stage the stripped copy (`git add`) and run `python tools/check_public_safety.py` to
confirm that it has no findings. The check reads only files that git tracks, so an image that
has not been added yet is not checked.

## What agents do

- Before posting on GitHub or committing, re-read the text for the items above.
- If something that looks personal is found in the repository or on GitHub, do not repeat it in
  a new comment or commit. Set `status:blocked` and tell the maintainer where it is, by file
  and line or by link.
- Git history cannot be cleaned by an agent. History rewriting, if needed, is the maintainer's
  decision before publication.
