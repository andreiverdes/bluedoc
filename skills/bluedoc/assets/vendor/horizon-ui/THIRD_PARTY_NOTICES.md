# Third-party notices

HorizonUI itself is licensed under Apache-2.0 by HorizonLoop SRL (see LICENSE and NOTICE). It depends on the following third-party
software. Versions are those installed at the time of writing; licences were checked with
`npm view <package> license`.

Full licence texts are in the `licenses/` folder next to this file, one per package, copied verbatim from the installed packages: `Inter-OFL-1.1.txt` and `JetBrainsMono-OFL-1.1.txt` (fonts, redistributed inside `dist/horizon-ui.css`), `react-MIT.txt`, `radix-ui-MIT.txt` (also covers the `@radix-ui/*` packages, which carry the same text), `lucide-react-ISC-MIT.txt` (ISC with MIT portions), `clsx-MIT.txt`, `tailwind-merge-MIT.txt`, `tailwindcss-MIT.txt` and `floating-ui-MIT.txt` (covers the `@floating-ui/*` packages). Anyone redistributing the built CSS must ship the two font licence files with it.

## React / React DOM

- Packages: `react`, `react-dom`
- Version: 19.3.0
- Licence: MIT
- Copyright: Copyright (c) Meta Platforms, Inc. and affiliates.
- Licence text: https://github.com/facebook/react/blob/main/LICENSE

## Radix UI

- Package: `radix-ui`
- Version: 1.6.7
- Licence: MIT
- Copyright: Copyright (c) 2022 WorkOS
- Licence text: https://github.com/radix-ui/primitives/blob/main/LICENSE

## Lucide

- Package: `lucide-react`
- Version: 1.49.0
- Licence: ISC (portions MIT)
- Copyright: Copyright (c) 2026 Lucide Icons and Contributors; portions Copyright (c) 2013-present Cole Bemis
- Licence text: https://github.com/lucide-icons/lucide/blob/main/LICENSE

## clsx

- Package: `clsx`
- Version: 2.1.1
- Licence: MIT
- Copyright: Copyright (c) Luke Edwards
- Licence text: https://github.com/lukeed/clsx/blob/master/license

## tailwind-merge

- Package: `tailwind-merge`
- Version: 3.7.0
- Licence: MIT
- Copyright: Copyright (c) 2021 Dany Castillo
- Licence text: https://github.com/dcastil/tailwind-merge/blob/main/LICENSE.md

## Tailwind CSS (build-time)

- Packages: `tailwindcss`, `@tailwindcss/cli`
- Version: 4.3.3
- Licence: MIT
- Copyright: Copyright (c) Tailwind Labs, Inc.
- Licence text: https://github.com/tailwindlabs/tailwindcss/blob/main/LICENSE

## Inter (font)

- Package: `@fontsource-variable/inter`
- Version: 5.3.0
- Licence: SIL Open Font License 1.1
- Copyright: Copyright 2016 The Inter Project Authors (https://github.com/rsms/inter)
- Licence text: https://github.com/rsms/inter/blob/master/LICENSE.txt

## JetBrains Mono (font)

- Package: `@fontsource-variable/jetbrains-mono`
- Version: 5.3.0
- Licence: SIL Open Font License 1.1
- Copyright: Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)
- Licence text: https://github.com/JetBrains/JetBrainsMono/blob/master/OFL.txt

## Caveat (font, website only)

- Used by: the website in `site/` (handwritten notes); not part of the npm package
- Licence: SIL Open Font License 1.1
- Copyright: Copyright 2014 The Caveat Project Authors (https://github.com/googlefonts/caveat)
- Licence text: `site/public/fonts/Caveat-OFL.txt`, published next to the font file

## Runtime dependencies installed with the package (ruling R98)

`radix-ui`, `lucide-react`, `clsx` and `tailwind-merge` are listed in `dependencies` and are external to `dist/index.js`: they are installed alongside HorizonUI, not copied into it. The packages below are what those dependencies pull in at runtime. Versions and licences are read from each package.json. Licence texts are in each package under node_modules and in its repository.

### Radix UI packages (MIT)

`radix-ui` and the `@radix-ui/*` packages it re-exports, same copyright holder as the Radix UI entry above:

- `@radix-ui/number` 1.1.3 (MIT)
- `@radix-ui/primitive` 1.1.7 (MIT)
- `@radix-ui/react-arrow` 1.1.15 (MIT)
- `@radix-ui/react-compose-refs` 1.1.5 (MIT)
- `@radix-ui/react-context` 1.2.2 (MIT)
- `@radix-ui/react-direction` 1.1.4 (MIT)
- `@radix-ui/react-dismissable-layer` 1.1.19 (MIT)
- `@radix-ui/react-id` 1.1.4 (MIT)
- `@radix-ui/react-popper` 1.3.7 (MIT)
- `@radix-ui/react-portal` 1.1.17 (MIT)
- `@radix-ui/react-presence` 1.1.10 (MIT)
- `@radix-ui/react-primitive` 2.1.10 (MIT)
- `@radix-ui/react-scroll-area` 1.2.18 (MIT)
- `@radix-ui/react-slot` 1.3.3 (MIT)
- `@radix-ui/react-tooltip` 1.2.16 (MIT)
- `@radix-ui/react-use-callback-ref` 1.1.4 (MIT)
- `@radix-ui/react-use-controllable-state` 1.2.6 (MIT)
- `@radix-ui/react-use-effect-event` 0.0.5 (MIT)
- `@radix-ui/react-use-layout-effect` 1.1.4 (MIT)
- `@radix-ui/react-use-size` 1.1.4 (MIT)
- `@radix-ui/react-visually-hidden` 1.2.11 (MIT)

### Other transitive packages

- `@floating-ui/core` 1.8.0 (MIT)
- `@floating-ui/dom` 1.8.0 (MIT)
- `@floating-ui/react-dom` 2.1.9 (MIT)
- `@floating-ui/utils` 0.2.12 (MIT)

`react`, `react-dom`, `react/jsx-runtime` are external peer dependencies. `lucide-react`, `clsx` and `tailwind-merge` are external dependencies listed above in their own sections.

This list reflects the Radix packages in use as of Task 6. When a later task uses more Radix primitives, add the packages it pulls in (for example react-remove-scroll, aria-hidden, tslib) from `npm ls --all radix-ui`.
