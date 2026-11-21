# Licences des bibliothèques de la vue 3D

La vue 3D du cerveau (`cerveau.html`) intègre deux fichiers de ce dossier, venus des paquets npm officiels
(versions et empreintes SHA-256 : `sources.json` ; fabrication : `fabriquer.py`) :

| Fichier | Paquet | Version | Licence |
|---|---|---|---|
| `3d-force-graph.min.js` | 3d-force-graph (Vasco Asturiano), copié tel quel | 1.80.0 | MIT |
| `three-fx.js` | three.js (`build/three.core.min.js`) et la passe de bloom (`examples/jsm/`) | 0.183.0 | MIT |

`3d-force-graph.min.js` embarque ses dépendances, toutes sous licence libre et permissive :

| Paquet | Licence | Copyright |
|---|---|---|
| three | MIT | © 2010-2026 three.js authors |
| three-forcegraph, three-render-objects, kapsule, accessor-fn, d3-force-3d, d3-binarytree, d3-octree, data-bind-mapper, float-tooltip | MIT | © 2017-2024 Vasco Asturiano |
| d3-array, d3-color, d3-dispatch, d3-format, d3-interpolate, d3-quadtree, d3-scale, d3-scale-chromatic, d3-selection, d3-time, d3-time-format, d3-timer, internmap | ISC | © 2010-2026 Mike Bostock |
| ngraph.graph, ngraph.forcelayout, ngraph.events, ngraph.random | BSD-3-Clause | © 2013-2026 Andrei Kashcha |
| ngraph.merge | MIT | © 2013-2019 Andrei Kashcha |
| @tweenjs/tween.js | MIT | © 2010-2012 Tween.js authors |
| polished | MIT | © 2016-Present Brian Hough and Maximilian Stoiber |
| preact | MIT | © 2015-present Jason Miller |
| tinycolor2 | MIT | © Brian Grinstead |
| lodash-es | MIT | © OpenJS Foundation and other contributors |
| @babel/runtime | MIT | © 2014-present Sebastian McKenzie and other contributors |

Les textes des trois licences suivent. Chacun vaut pour les titulaires du copyright nommés ci-dessus.

## MIT

Copyright (c) 2010-2026 three.js authors
Copyright (c) 2017-2024 Vasco Asturiano
Copyright (c) 2013-2019 Andrei Kashcha
Copyright (c) 2010-2012 Tween.js authors
Copyright (c) 2016-Present Brian Hough and Maximilian Stoiber
Copyright (c) 2015-present Jason Miller
Copyright (c) Brian Grinstead
Copyright OpenJS Foundation and other contributors
Copyright (c) 2014-present Sebastian McKenzie and other contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

## ISC

Copyright 2010-2026 Mike Bostock

Permission to use, copy, modify, and/or distribute this software for any purpose
with or without fee is hereby granted, provided that the above copyright notice
and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS
OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER
TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF
THIS SOFTWARE.

## BSD-3-Clause

(texte de ngraph.graph ; les autres paquets ngraph sous BSD-3-Clause ont le même, © 2013-2025 Andrei Kashcha)

Copyright (c) 2013 - 2026, Andrei Kashcha
All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

  Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

  Redistributions in binary form must reproduce the above copyright notice, this
  list of conditions and the following disclaimer in the documentation and/or
  other materials provided with the distribution.

  Neither the name of the Andrei Kashcha nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
