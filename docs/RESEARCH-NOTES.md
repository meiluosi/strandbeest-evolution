# Research Notes

Every claim needs a source. Mark `[unverified]` until checked.

## Theo Jansen's evolution periods
Source status: strandbeest.com is rendered dynamically and could not be fetched here, so the primary source is **not yet checked**. The list below comes from a summary of the Wikipedia article "Strandbeest" (https://en.wikipedia.org/wiki/Strandbeest), cross-read against press coverage. Verify against strandbeest.com before quoting years in print.

| Period | Years | Change as summarised |
|---|---|---|
| Pregluton | 1986–1989 | early concepts and drawings |
| Gluton | 1990–1991 | built mainly with adhesive tape |
| Chorda | 1991–1993 | cable ties (zip ties) |
| Calidum | 1993–1994 | heat-formed PVC tubing; joints became brittle |
| Tepideem | 1994–1997 | creatures designed to live as groups |
| Lignatum | 1997–2001 | wood used for a while |
| Vaporum | 2001–2006 | pneumatic pressure for propulsion independent of the wind |
| Cerebrum | 2006–2008 | primitive sensing of the environment |
| Suicideem | 2009–2011 | pressure-driven pistons overloaded the joints |
| Aspersorium | 2012–2013 | tail-wagging mechanisms |
| Aurum | 2013–2015 | low-wind operation |
| Bruchum | 2016–2019 | caterpillar-like motion |
| Volantum | 2020–2021 | flying strandbeests |

Press coverage (Designboom, Colossal, 2022) agrees on 1990 as the start, "twelve periods of evolution", and Volantum as the latest: https://www.designboom.com/art/theo-jansen-strandbeests-fly-04-21-2022/ , https://www.thisiscolossal.com/2022/04/theo-jansen-flying-strandbeest/ .

- The same coverage gives Animaris Vulgaris (first beach animal, reportedly 28 legs, did not manage to stand) and Animaris Currens Vulgaris (1991, nylon zip ties); and Animaris Percipiere Rectus (2005), Ordis (2006), Umerus (2009).
- [unverified] That the first Currens Vulgaris is dated 1990 in some sources and 1991 in others; resolve from strandbeest.com.
- [unverified] Any claim about exactly how the walkers sense water or anchor in storms: the sensing is described as primitive; mechanisms are not documented here.
- The leg geometry is described as found by evolutionary computation, inspired by Dawkins (Wikipedia). Jansen's actual fitness function and algorithm are **not** documented in the sources above; our own GA (docs/EXPERIMENTS.md) is a reconstruction of the idea, not of his method.

## Jansen linkage lengths ("holy numbers")
- Lengths a=38.0 b=41.5 c=39.3 d=40.1 e=55.8 f=39.4 g=36.7 h=65.7 i=49.0 j=50.0 k=61.9 l=7.8 m=15.0 — confirmed against https://en.wikipedia.org/wiki/Jansen%27s_linkage (m is the crank; the page does not give the joint topology).
- Topology: K=circ(C,j;G,b) L=circ(K,e;G,d) M=circ(C,k;G,c) N=circ(L,f;M,g) F=circ(M,i;N,h), crank pivot at (a, l) from ground pivot G. From arXiv 2606.22129 (durability-aware optimization of the Jansen linkage), found via search; we did not read the paper in full. Independently, a brute-force search over topologies for a flat-stroke foot path produced this same assignment among its candidates, and the resulting path is D-shaped (flat ground stroke ~43% of the cycle, lift ~33% of width).
- Branch signs are our choice, picked so the foot is the lowest point of the leg.
