# The five bars (until 2026-10-26)

Muzix's first mark: five upright colour bars of different heights on a Midnight
Navy plate. It was dropped on 2026-10-26 because it looked too much like other
players' spectrum-bar marks (PRODUCT.md), but Unraid's Docker icon kept it until
2026-11-11. `unraid/muzix.png` is that icon (the template, unraid/muzix.xml, points
to the file of that name in the repo). To go back, copy it over the one in use:

```sh
cp docs/icons/bars/unraid/muzix.png unraid/muzix.png
```

Unraid keeps its own copy of a container's icon (Muzix-icon.png in
/var/lib/docker/unraid/images and in dynamix.docker.manager's images), so that
copy has to be replaced too before the Docker tab shows the change.
