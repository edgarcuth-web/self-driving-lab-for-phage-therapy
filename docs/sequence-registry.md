# Local sequence registry v1

## Purpose and boundary

The SDL sequence registry binds exact local FASTA files to normalized sequence
fingerprints. PADLOC and other scientific analyzers use this registry to ensure
they analyze the exact host genome named by HostState. HostState/PhageProfile
identity and model-request resolution remain SDL domain responsibilities; the
model repository does not read this local registry.

Sequence resolution is an integrity and identity check only. It does not confirm
that the source database annotation is correct, that a sequence belongs to the
claimed organism, that the isolate is pure, or that any biological feature or
interaction prediction is valid. It does not fetch remote content, derive
features, train models, or run inference.

## Two different SHA-256 digests

Each registered FASTA has two distinct fingerprints:

- `file_sha256`: SHA-256 of the exact original file bytes, including headers,
  line endings, wrapping, case, and any UTF-8 byte-order mark.
- `sequence_sha256`: SHA-256 of normalized contigs, matching the existing lab
  `phage_lab/biology.py::read_fasta` convention.

The normalized digest is computed as follows:

1. Decode UTF-8, accepting an optional UTF-8 BOM, and use universal newline
   handling.
2. Ignore blank lines and FASTA header text. A header is a non-empty line
   beginning with `>` after surrounding whitespace is stripped.
3. For each header, append one NUL byte (`0x00`) to the digest input.
4. For each sequence line, strip surrounding whitespace, convert bases to
   uppercase, validate against `ACGTRYSWKMBDHVN`, then append the ASCII bases.
5. The normalized base count is the sum of bases across all contigs.

In other words, for contigs `ACGT` and `NRY`, the hashed bytes are
`NUL + ACGT + NUL + NRY`. Headers, whitespace, line wrapping and letter case do
not affect `sequence_sha256`, but they do affect `file_sha256`. Each contig
boundary is retained, so different contig segmentation does affect the digest.

The current limits match the lab's genome reader: 20 million total bases and
40,000,000 original file bytes. Empty contigs, empty headers, sequence before a
header, invalid symbols, malformed UTF-8, and empty FASTA files are rejected.
FASTA headers are not used as an identity source.

## Manifest format

A sequence registry is a JSON object with exactly these top-level fields:

- `schema_version`: integer `1`;
- `registry_id`: a non-empty local identifier;
- `entries`: a list of local FASTA mappings.

The machine-readable contract is
[`sequence-registry-v1.schema.json`](../schemas/sequence-registry-v1.schema.json).

Every entry requires:

- `kind`: `host_genome` or `phage_sequence`;
- `sequence_sha256`: expected normalized sequence digest;
- `file_sha256`: expected original file-byte digest;
- `path`: POSIX-style path relative to the sequence registry file;
- `status`: `available` or `withdrawn`.

A phage-sequence entry may also include `accession` and
`source_snapshot_sha256`. When the PhageProfile names an accession, the
registered accession must match. If the profile also names a retrieved-source
snapshot SHA-256, the entry must carry the same snapshot digest. Host-genome
entries cannot declare phage accession or snapshot fields.

Host-genome digests must be unique; phage accession plus source-snapshot digest
must identify at most one entry; file paths must be unique. Absolute paths,
`.`/`..` components, backslashes, missing files, and symlinks that escape the
registry directory are rejected. The resolver only uses paths from the locally
managed registry.

## Resolution rules

For the current host-only PADLOC path, the resolver:

1. matches the HostState `host_genome_sha256` to one `host_genome` entry;
2. rejects missing, withdrawn or ambiguous entries;
3. resolves the registry-relative path and rejects traversal or escaping symlinks;
4. checks the exact file-byte digest and recomputes the normalized sequence digest;
5. checks base count and contig count from the same verified file.

The registry also supports `phage_sequence` entries with optional accession and
pinned source-snapshot provenance. Those fields are intended for future SDL phage
annotation pipelines; they are not a model-side resource-resolution mechanism.

The audit summary reports both digests, base/contig counts, and registry-relative
paths. It never includes raw sequence content. Successful resolution establishes
local identity and integrity only, not organism identity, annotation correctness,
or biological validity.

## Usage

Create a one-entry registry for a FASTA file. Keep the manifest in the same
directory as the FASTA, or in a parent directory that contains it:

```bash
python -m phage_lab create-sequence-registry \
  --fasta data/host/host.fna \
  --registry-id host-isolate-001-sequences-v1 \
  --out data/host/sequence-registry.v1.json
```

This command never overwrites an existing registry or modifies/copies the FASTA.
It emits both the raw-file and normalized-sequence digests. To run PADLOC, the
HostState `host_genome_sha256` must match the normalized digest in this registry:

```bash
python -m phage_lab annotate-host-defense-padloc \
  --host-state data/host/host-state.v1.json \
  --sequence-registry data/host/sequence-registry.v1.json \
  --padloc-data "$PADLOC_DATA" \
  --outdir runs/padloc-host-001
```

## Next boundary

The sequence registry is consumed by the real [PADLOC host-defense adapter](padloc-adapter.md). Each successful analysis produces a [FeatureArtifact v1](feature-artifact.md) with exact input, tool, database, output and limitation provenance.
