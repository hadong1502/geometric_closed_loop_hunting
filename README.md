# Closed-loop Probabilistic Escape
This folder has the code for implementing a Probabilistic Closed-loop Escape model, developed based on the Closed-loop Classical Escape by Leo Li's at https://github.com/haohao1331/rot2-project. In this system, a gantry-controlled artificial prey will attempt to escape a mouse, both being detected by an OpenMV camera from the bird-eye view. Positions of both objects are tracked to calculate a geometric escape trajectory for the prey, which follows the model proposed by Domenici et al. 2008 (10.1016/j.cub.2008.09.062). The advantage of this closed-loop system is that the prey will run in a somewhat predictable trajectory, which is a close depiction of the naturalistic hunting process.  

# Reference
- Domenici P, Booth D, Blagburn JM, Bacon JP. Cockroaches keep predators guessing by using preferred escape trajectories. Curr Biol. 2008 Nov 25;18(22):1792-6. doi: 10.1016/j.cub.2008.09.062. Epub 2008 Nov 13. PMID: 19013065; PMCID: PMC2678410.
- [Leo Li's original model](https://github.com/haohao1331/rot2-project)
- [Leo Li's rotation report](docs/Rotation%20Report.pdf)