# Research Notes

Every claim needs a source. Mark `[unverified]` until checked.

## Additional external-data screening (2026-11-04)

- [Compliant-linkage toolkit README, pinned commit bb613745](https://github.com/MeghRaval30/compliant-linkage-toolkit/blob/bb6137456a04d9afaa51240e9fc3e8540d269532/README.md): the author explicitly states **“No physical measurements exist yet.”** The [data README](https://github.com/MeghRaval30/compliant-linkage-toolkit/blob/bb6137456a04d9afaa51240e9fc3e8540d269532/data/README.md) describes future bulk-data releases; the inspected directory has `.gitkeep` and that README only. Our conclusion: not a currently usable measured-data source. Its software/simulated outputs do not satisfy H4-01.
- [Fariansyah and Setiawan, *Rancang Bangun dan Pengujian Kendaraan Berkaki Empat*, IPB University, 2025](https://repository.ipb.ac.id/handle/123456789/171642): repository abstract describes a Jansen prototype and functional/soil testing. Review was limited to the metadata/abstract. Fulltext and appendix retrieval returned cache misses; raw samples, instrument calibration, uncertainty and reuse rights are **[unverified]**. No reported torque/power summary is adopted as a calibrated observation. The source remains a candidate, not accepted validation.

Review scope and retrieval outcomes are recorded in `experiments/external-data-followup-2026-11-04.json`; no measured samples or third-party bulk files were added.

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

## Literature foot path measurements (Pop et al. 2014) — source review 2026-11-03

- Citation: Pop, F., Dolga, V., & Pop, C. (2014). *Analysis of the Trajectory Shape Described by a Robotic Leg during a Walking Sequence*. Applied Mechanics and Materials 658, 684–689. [Publisher / DOI](https://www.scientific.net/AMM.658.684).
- **Verified from the publisher abstract**: a physical Jansen prototype, foot marker, CCD tracking and a **DC motor**. The former claim “stepper motor” was incorrect and is withdrawn.
- **[unverified]** The retained file `experiments/literature-jansen-amm2014.json` attributes 24 coordinates, a 57.1 mm stroke, 22.5 mm lift, 0.43 duty factor and ±0.8 mm digitization uncertainty to this paper. The abstract does not report them. The repository has no original plot/raster hash, pixel coordinates, axis calibration, extraction log or uncertainty derivation. The historical assertion of Fig. 4/5 and 300 dpi is not independently recoverable.
- **[unverified]** The historical fair-use note is not a verified license grant. The publisher page states all rights reserved. No new copy of the paper or figure is redistributed here.
- **Result**: preserve the numbers for audit; suspend their use as E2 evidence. Default `scripts/verify_literature_kinematics.py` exits 2; `--unverified-preview` only reproduces a numerical comparison. Close agreement cannot authenticate a source. See EXPERIMENTS §46.

## External-data search for H4-01 (2026-11-03)

| Primary source | What was verified | Scope / remaining gaps |
|---|---|---|
| Nansai et al., 2015, [On a Jansen leg with multiple gait patterns for reconfigurable walking platforms](https://journals.sagepub.com/doi/full/10.1177/1687814015573824), DOI 10.1177/1687814015573824 | The Performance section reports ten-cycle prototype trajectories; Table 2 compares measured and simulated dimensions. Standard-gait width is 33.42 vs 39.82 cm, height 7.59 vs 9.39 cm. | A usable primary geometry reference; it does **not** establish agreement with our geometry. The cited 1 N·m is from a separate dynamics paper, not a measured torque trace in this experiment. No start-wind data or independent calibration/held-out trace verified. |
| Röder, Ebel & Eberhard, 2024, [Motion and Motor-Current Data of a Four-Bar Linkage](https://doi.org/10.18419/DARUS-4152), DaRUS v1.0 | Public physical measurements, repeated trials, position/velocity/current/voltage with units; linkage dimensions and Dynamixel XH430-W350-R instrument are described. Dataset page specifies CC BY 4.0. | Candidate for four-bar subsystem identification, **not** a Jansen walker or wind-start experiment. Current is not calibrated output torque. Mass/inertia, torque calibration and measurement uncertainty still need verification before use. No model validation or evidence upgrade has been performed. |

The DaRUS metadata and README plus three empty-load Bridge_0 trials were fetched and their provider checksums verified. File IDs, SHA-256, units and sampling diagnostics are recorded in `experiments/external-fourbar-source-review-2026-11-03.json`; raw files are not redistributed. The README also lacks a calibrated output-torque conversion and absolute measurement uncertainty.

Follow-up primary-source review (2026-11-03): [Wohlleben et al., 2024, DOI 10.1002/pamm.202400027](https://doi.org/10.1002/pamm.202400027), §3 and Fig. 2, directly uses this dataset. **Source facts:** it describes a three-body four-bar model with masses/inertias supplied to Neweul-M², but reports no numerical mass/inertia or current-to-shaft-torque calibration. Its experiments use the honey/stirrer condition. The dataset's 75-file inventory contains no CAD/model/calibration attachment; its [tutorial notebook](https://darus.uni-stuttgart.de/api/access/datafile/290242) only parses and plots signals. No experiment-specific calibration date or absolute instrument uncertainty was found in these reviewed materials. This is a bounded finding about the public sources checked, not a claim that the authors never measured these quantities.

The [ROBOTIS XH430-W350 official manual](https://emanual.robotis.com/docs/en/dxl/x/xh430-w350/) specifies 4096 position counts/revolution, 0.229 rpm velocity increments, 2.69 mA current increments, a 353.5:1 gear ratio, and 0.25° backlash. These are nominal specifications, **not** calibrated standard uncertainties. Its stall-torque/current ratings do not establish a calibrated conversion for this experiment's small, varying currents.

**Our inference / validation boundary:** without an independently known absolute mechanical or torque scale, scaling all inertial terms, torque gain and friction together preserves the ideal horizontal mechanism's angular dynamics; current/angle/velocity alone therefore cannot generally identify those absolute scales separately. Three repetitions can estimate repeatability, not remove this ambiguity or certify absolute accuracy. A future frozen-parameter, held-out waveform/repetition test could assess angular prediction under stated assumptions. If measured current is supplied as input, that same current is not an independent predicted output; predicting current from commanded current also requires a controller/electrical model. The current walker Scenario lacks fixed-base and per-link inertial parameters plus a time-varying current-drive contract. A dedicated adapter using the same MuJoCo backend is still required; derived coupler motion must not be counted as an independently measured foot path. No dynamics validation or Jansen/wind evidence upgrade follows from this review.

A public dataset, a paper citation and a successful fit are separate milestones. H4-01 remains open until the relevant physical quantity has traceable input, an appropriate forward model and an independent held-out comparison.

### Additional primary-source screening (2026-11-04)

- Biel & Routt, [Strandbeest Project, Red Rocks Community College, Spring 2020](https://www.rrcc.edu/sites/default/files/u2855/Strandbeest%20Project%20-%20Nicholas%20Biel%2C%20Michelle%20Routt.pdf): a physical kit/fan experiment. The authors state that wind was estimated without an anemometer, timing was imprecise, and minimum starting wind could not be determined. This is a useful community lead, but does not provide the calibrated start-wind/torque and held-out raw records needed for H4. No figures or inferred numerical points are imported.
- Wang, [arXiv:2606.22129v2](https://arxiv.org/html/2606.22129v2), §§2–3 and §7: the topology and inverse-dynamics equations are directly inspectable. The conclusion explicitly lists absence of experiment as a limitation; prescribed stance load and ideal joints make this a numerical-method reference, not real-world validation data. This updates the earlier note that only search results had been consulted; no experimental evidence level is assigned.

The [DaRUS four-bar source](https://doi.org/10.18419/DARUS-4152) remains a promising **subsystem** candidate with repeated raw measurements; the missing absolute mechanical/torque scale and appropriate forward adapter described above are unchanged. This screening found no new dataset that closes H4-01; it does not assert that no such data exist elsewhere.

### Ingram primary-source follow-up (2026-11-04)

Ingram, *A new type of mechanical walking machine*, University of Johannesburg: the PDF title page says **November 2006**; the [repository record](https://ujcontent.uj.ac.za/esploro/outputs/doctoral/A-new-type-of-walking-machine/9910029207691) displays a 2008 date. The university PDF was downloaded and §§8.3.1–8.3.3 (printed pp.146–153) read, including visual checks of the method and Fig.79. It reports physical walking experiments. Torque is inferred from electrical power and crank speed, then suspended-walker losses are subtracted. The method uses voltage traces, a 0.1-ohm shunt and cam/switch timing. Detailed records are attributed to an accompanying CD-ROM; the current repository lists only the PDF. The discussion limits agreement to order of magnitude.

**Our assessment:** electrical input divided by angular speed is not independently calibrated mechanical torque; no-load subtraction does not establish load-dependent motor/transmission losses. No reusable raw traces, absolute uncertainty, independent holdout or reuse license were verified in this review. No points were digitized or fitted. Source hash, page scope and missing fields are recorded in `experiments/external-ingram-source-review-2026-11-04.json`. This is a stronger experimental lead, but H4-01 remains unaccepted.


### MuJoCo contact-parameter semantics (2026-11-04)

Primary source: [MuJoCo Modeling, Solver parameters / Reference](https://mujoco.readthedocs.io/en/stable/modeling.html#reference), consulted 2026-11-04. The direct solref pair describes mass-normalised stiffness/damping in the constraint acceleration. Equating its formulas with the positive time-constant/damping-ratio form gives `damping = 2*zeta*sqrt(stiffness)`; impedance scaling is already accounted for. An extra estimated body/support mass is not part of this conversion. The documented constant-impedance equations supply an independent one-DOF contact oracle, tested in native MuJoCo 3.17.0 and WASM 3.14.0; evidence and limitations are in EXPERIMENTS §59. This validates an implementation convention, not the contact stiffness/friction of a real printed foot.

Follow-up 2026-11-04: MuJoCo's [friction cones](https://mujoco.readthedocs.io/en/stable/computation/index.html#friction-cones), [solver settings](https://mujoco.readthedocs.io/en/stable/modeling.html#solver-settings) and [preventing slip](https://mujoco.readthedocs.io/en/stable/modeling.html#preventing-slip) distinguish contact-model choices from solver accuracy. Regularisation can permit slip inside the cone. Elliptic cones/impratio and NoSlip are not interchangeable with simply increasing the iteration budget. Our 16-trial diagnostic retains a stalled NoSlip case and a larger loop-closure error; it promotes no contact default (EXPERIMENTS §65).

### Gas control-volume energy (2026-11-04)

Primary source: MIT Unified Engineering, [Control volume form of the system laws, §§2.5.2 and 2.5.4.1](https://web.mit.edu/16.unified/OldFiles/www/SPRING/thermodynamics/notes/node18.html). Mass entering a volume transports enthalpy, including flow work; a rigid adiabatic filling tank receives that incoming enthalpy. This supplies an independent first-law check for the ideal-gas network. Our implementation uses constant air heat capacities, corrects upstream energy transport, and explicitly separates the assumed polytropic/thermostat heat from mechanical work (EXPERIMENTS §66). Those closures and the component defaults are model assumptions, not measurements or an externally validated model of a Jansen pneumatic system.

### Additional external dynamics sources (2026-11-04)

- Hermus, Doeringer, Sternad and Hogan, [Crank Turning Data](https://zenodo.org/records/10059390), DOI 10.5281/zenodo.10059390. The provider API confirms CC BY 4.0. A bounded archive inspection retrieved the README and one raw trial; hashes and sampling diagnostics are in `experiments/external-dynamics-candidates-2026-11-04.json` and EXPERIMENTS §67. The README identifies rad/rev/s/N columns but leaves moment units unspecified. Its mixed 200/100 Hz acquisition requires explicit alignment; raw availability is not a calibration certificate.
- The associated [Hermus et al. 2020 primary paper](https://jameshermus.github.io/assets/pdf/Hermus_2020.pdf), DOI 10.1152/jn.00536.2019, describes a 10.29 cm horizontal crank, ATI 15/50 transducer and 0.0004 degrees/count encoder. The author-hosted full PDF is now verified, superseding the earlier search excerpt. Appendix A reports inertia 3.716e−3 but visibly prints kg/m²; Eq A2 requires kg·m² dimensionally. A likely printing error is an inference, not an accepted measurement correction. EXPERIMENTS §69 and `experiments/external-crank-methods-review-2026-11-04.json` preserve that earlier review. The subsequent author-code review below resolves the nominal inertia unit and force mapping; absolute force uncertainty and precise timing remain unverified. This human-driven crank does not validate a Jansen walker or wind startup.
- [Doeringer 1999 MIT thesis](https://dspace.mit.edu/entities/publication/06800448-3f71-42b0-a514-d242ae9236bb), *An investigation into the discrete nature of human arm movements*: original experiment lead identified in the primary publisher metadata. Direct retrieval returned HTTP 429; no thesis contents or checksum are claimed verified, and its viewing terms must not be confused with the raw dataset license.
- The provider metadata also links the authors' [2023 analysis repository](https://github.com/jameshermus/crankTurning-dynamicPrimitives/tree/ec444fa3de1b1727383eaa776e74581691cfa587), MIT-licensed and now checked at that exact commit. In `trialAnalysis.m`, line 30 explicitly uses kg·m² for crank inertia and line 118 supplies 3.716e−3 with an outboard correction comment, resolving the paper's dimensional typo for this source model. Lines 206–216 identify normal/tangential force columns; condition mappings and the Cartesian transform are present. Instrument uncertainty is still missing. EXPERIMENTS §71 records 32 source-verified trials, a preregistered 16-trial holdout, and the simple model's failed medium-speed adequacy check. Future confirmation must use fresh holdouts.
- Bjelonic and Hutter, [PACE Dataset for Sim-to-Real Transfer in Legged Robots](https://doi.org/10.3929/ethz-c-000783505). The publisher search snapshot reports version 1.0, September 2025, CC BY 4.0 and joint/leg/actuator records; direct retrieval returned 403, so actual raw arrays and license-file contents remain unchecked. The [authors' repository](https://github.com/leggedrobotics/pace-sim2real) is a separate Apache-2.0 code source; its inspected README blob is `7d54503a7f2aa6cbd9423bea774a956f830a0e1d`. Its example collects simulated trajectories, which must not be substituted for the external measurements.

Both sources remain candidates. No Measurement/Profile, calibrated holdout or evidence upgrade was produced by this screening.
