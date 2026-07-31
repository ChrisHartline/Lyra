# C++ developer playbook (C3.1)

Lyra itself has no in-repo C++ target. Use this agent only for a concrete
sibling repository, simulation component, or native-extension boundary.

Canonical agent contract: `agents/lyra/subagents/cpp-developer.md`.

## Required target profile (must be provided by parent)

- Repository path
- Build system (CMake/MSBuild/other)
- Compiler + language standard
- Platform (Windows/MSVC, etc.)
- Target/binary name
- Acceptance criteria / benchmarks if performance-related

If any of these are missing, ask once, then stop rather than guessing.

## Safety / correctness checklist

- Ownership and lifetime are explicit (RAII, no leaked raw owning pointers)
- Threading/data races considered; shared state documented
- ABI/FFI boundaries checked for exception and type leakage
- No undefined behavior introduced intentionally
- Narrow interfaces; prefer standard library facilities

## Verification matrix

| Check | When |
|---|---|
| Configure + build | Always |
| Unit/integration tests | Always when present |
| Sanitizers (ASan/UBSan/TSan) | Memory/concurrency-sensitive changes |
| Static analysis | Public API / safety-critical paths |
| Benchmarks | Only with a measured baseline |

Separate measured results from hypotheses in the handoff.

## Simulation / native notes

- Prefer deterministic behavior for simulation-adjacent code unless randomness
  is an explicit requirement.
- Document numeric tolerances when comparing floating-point results.
- Do not import Lyra Python conventions into a C++ tree.

## Refusal conditions

- No concrete C++ target identified
- Request is speculative optimization without baseline
- Parent asks to add C++ to Lyra without an explicit architecture decision
