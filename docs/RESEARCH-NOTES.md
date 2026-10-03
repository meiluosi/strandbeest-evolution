# Research Notes

Every claim needs a source. Mark `[unverified]` until checked.

## Theo Jansen's evolution periods
Primary source: the period pages on strandbeest.com/evolution/<period>, read in a browser on 2026-10-04 (the site renders client-side, so plain HTTP fetches return nothing). The home page says the strandbeests "have evolved since their inception in 1990 and have been divided into 12 periods". Years below are those printed on each period page.

| Period | Years | Verified content (paraphrased) |
|---|---|---|
| Gluton | 1990–1991 | tubes joined with adhesive tape; Vulgaris could not stand or walk |
| Chorda | 1991–1993 | nylon cable ties; Currens Vulgaris first to stand and walk; leg ratios ("sacred numbers") calculated with a genetic algorithm on his Atari computer; leg made of triangles |
| Calidum | 1993–1994 | heat gun; identical parts from moulds; joints brittle after a year ("osteoporosis") when the gun was used too hot |
| Tepideem | 1994–1997 | herd debuts (shelter from wind); Ancora with roller anchor, turns downwind |
| Lignatum | 1997–2001 | wood-pallet sandwich construction; Rhinoceros Transport (Sept 2004: 3.2 t, 4.7 m tall) walked too fast and joints gave way |
| Vaporum | 2001–2006 | self-propulsion: plastic-bottle "stomach" filled by wind-driven pumps; sliding-tube pneumatic "muscles" (Excelsus muscles: 2 kg, ~100× its weight in force) |
| Cerebrum | 2006–2008 | water feeler (hose), soft-sand feeler (muscle pressure), analogue pedometer "witching rod"; reflex: turn round |
| Suicideem | 2009–2011 | Umerus shoulder-pump drive broke its own backbone on sand (walked 26 s on the beach); Siamesis (72 legs) same; converted back to the Percipiere system |
| Aspersorium | 2012–2013 | wagging tail (Adulari) |
| Aurum | 2013–2015 | weak wind: big sails; minimum starting wind about 15 km/h |
| Bruchum | 2016–2019 | jointless caterpillars, 64 pneumatic muscles on one |
| Volantum | 2020–2021 | Ader flies up to 6 m to avoid sand burial, anchored to a post; Multi Tripodes (2020, 36 legs) too heavy to fly |

Still unverified or not on his pages:
- **Pregluton (1986–1989)**: appears in Wikipedia's list as an initial period, but the page on his site was empty when read; the site's home page describes Vermiculus Antramentum (1989) as the first life-form, a straight rod on a computer screen. His own count of periods is 12 (Gluton … Volantum).
- Animaris Vulgaris having 28 legs: press coverage only (Designboom / Colossal); the Gluton page gives no leg count.
- "Inspired by Dawkins": Wikipedia wording only.
- Dates of Animaris Ordis (2006) and Percipiere Rectus (2005): press coverage; the Cerebrum page shows a 2005 Percipiere Rectus photo but the page text was truncated when read.
- His actual fitness function and algorithm for the leg lengths are **not** documented on the pages read. Our GA (docs/EXPERIMENTS.md) reconstructs the idea, not his method.

Earlier secondary sources used before the primary check: https://en.wikipedia.org/wiki/Strandbeest , https://www.designboom.com/art/theo-jansen-strandbeests-fly-04-21-2022/ , https://www.thisiscolossal.com/2022/04/theo-jansen-flying-strandbeest/ .

## Jansen linkage lengths ("holy numbers")
- Lengths a=38.0 b=41.5 c=39.3 d=40.1 e=55.8 f=39.4 g=36.7 h=65.7 i=49.0 j=50.0 k=61.9 l=7.8 m=15.0 — confirmed against https://en.wikipedia.org/wiki/Jansen%27s_linkage (m is the crank; the page does not give the joint topology).
- Topology: K=circ(C,j;G,b) L=circ(K,e;G,d) M=circ(C,k;G,c) N=circ(L,f;M,g) F=circ(M,i;N,h), crank pivot at (a, l) from ground pivot G. From arXiv 2606.22129 (durability-aware optimization of the Jansen linkage), found via search; we did not read the paper in full. Independently, a brute-force search over topologies for a flat-stroke foot path produced this same assignment among its candidates, and the resulting path is D-shaped (flat ground stroke ~43% of the cycle, lift ~33% of width).
- Branch signs are our choice, picked so the foot is the lowest point of the leg.
