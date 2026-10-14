# Licensing

**Everything in this repository is licensed under [Apache-2.0](LICENSE)** from the founding commit. The Founding Assembly can keep that or change it (ballot 3).

## Why Apache-2.0 to start

- **It keeps every option open.** Apache-2.0 code can be carried into a GPLv3 or AGPLv3 project later, but not the other way round. We use the DCO and no CLA, so nobody can relicense other people's contributions. If we started under AGPL, going permissive later would need every contributor to agree. Starting under Apache means the Assembly can still choose anything.
- **Members can actually take part.** Most of us work for ad tech companies, and some companies' open source policies forbid AGPL code outright. Google's, for example, says AGPL code "MUST NOT be used at Google" and bans it from workstations without special approval. An AGPL project would lock some members out of their own network.
- **It includes a patent grant.** Each contributor grants users a licence to any of their own patents that their contribution would otherwise infringe, which makes employer approval easier.
- **It matches the Charter.** "If you want to commercialise it, fork it: the licence lets you."

## The trade-off

Apache-2.0 lets a company run a modified, closed copy of the seller without sharing its changes. AGPL-3.0 prevents that, which is why EthicalAds' ad server uses it. We think the network's real protection is its members, its name and its relationships with developers and advertisers, none of which a fork gets. But it is a fair argument, and the Assembly should have it.

## Ballot 3

| Option | What it means |
|---|---|
| **(a)** AGPL seller, MIT client, CC BY-SA docs | Nobody can run a closed fork of the network. Some members' employers may block them from contributing to the seller. |
| **(b)** Apache-2.0 everywhere (recommended) | What we have now. Simplest, and open to everyone's employer. |
| **(c)** AGPL everywhere | Strongest protection. Also slows `adterm` adoption, since some developers can't install AGPL tools at work. |

If the Assembly picks (a) or (c), future versions move to the new licence; anything already released stays available under Apache-2.0. Record the result in `decisions/`.

## Adding licence texts

Copy licence texts from their official sources, never from memory or a model:

- Apache-2.0: https://www.apache.org/licenses/LICENSE-2.0.txt (the copy in `LICENSE` matches the text bundled with several Apache-licensed Python packages)
- AGPL-3.0: https://www.gnu.org/licenses/agpl-3.0.txt
- MIT: https://opensource.org/license/mit
- CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/legalcode.txt

Contributions are made under the Developer Certificate of Origin (see [CONTRIBUTING.md](CONTRIBUTING.md)), so there is no CLA and no single party that can relicense the project.
