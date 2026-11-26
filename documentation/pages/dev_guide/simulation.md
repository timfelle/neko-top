# Simulation {#simulation}

\tableofcontents

\attention This is under construction, but should describe the notion of a
simulation. 

## Source terms {#source_term}
\attention This is under construction.

\warning The five source terms that Neko-TOP registers in Neko's registry
(`simple_brinkman`, `adjoint_brinkman_dissipation`,
`adjoint_viscous_dissipation`, `adjoint_scalar_convection` and
`adjoint_mixing_scalar`) are built in code, by the design, the objectives and
the adjoint. They cannot be selected from a case file: their `init_from_json`
is empty, so an entry of one of these types in `source_terms` (or in
`case.adjoint_fluid.source_term`) would be allocated without being initialised.
The case-file schema rejects them.

### Brinkman source term {#source_brinkman}

### Viscous dissipation {#source_dissipation}

### Brinkman dissipation {#source_lube}

### Scalar mixing {#source_scalar_mixing}

### Scalar convection {#source_scalar_convection}
