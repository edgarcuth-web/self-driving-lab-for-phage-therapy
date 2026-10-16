import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.biology import GenomeSummary
from phage_lab.host_profile import new_host_profile, write_host_profile
from phage_lab.measurement import Measurement
from phage_lab.phenotype import Phenotype, PhenotypeAssessor
from phage_lab.host_state import (
    HostStateComponent,
    HostStateEvidence,
    HostStateReference,
    host_state_component_from_dict,
    host_state_evidence_from_measurement,
    host_state_evidence_from_phenotype,
    host_state_from_dict,
    host_state_reference,
    load_host_state,
    new_host_state,
    write_host_state,
)


DIGEST = "a" * 64
T0 = "2026-10-16T12:00:00+00:00"
T1 = "2026-10-16T13:00:00+00:00"
T2 = "2026-10-16T14:00:00+00:00"


def profile(host_id="isolate-001", digest=DIGEST):
    return new_host_profile(
        host_id,
        GenomeSummary(sha256=digest, bases=5_000_000, contigs=1),
        created_at=T0,
    )


def evidence(
    *,
    evidence_id="ev-001",
    host_profile_id="isolate-001:v1",
    observed_at=T1,
    kind="phenotype",
):
    return HostStateEvidence(
        evidence_id=evidence_id,
        host_profile_id=host_profile_id,
        kind=kind,
        reference_id="phenotype-001:v1",
        reference_sha256="b" * 64,
        observed_at=observed_at,
        relation="supports the current admitted host-state component",
        details={"assay_context": "screen"},
    )


def component(evidence_id="ev-001"):
    return HostStateComponent(
        domain="phenotype_history",
        name="growth_response_to_prior_phage",
        value="negative",
        basis="observed",
        evidence_ids=(evidence_id,),
        note="Explicit historical phenotype; not generalized susceptibility.",
    )


class HostStateTests(unittest.TestCase):
    def test_initial_snapshot_can_be_empty_without_copying_host_profile_features(self):
        p = profile()
        state = new_host_state(
            p,
            host_state_id="host-state-001",
            as_of=T1,
            created_at=T1,
        )
        payload = state.to_dict()

        self.assertEqual(state.record_id, "host-state-001:v1")
        self.assertEqual(state.host_profile_id, p.profile_id)
        self.assertEqual(state.host_genome_sha256, p.genome.sha256)
        self.assertEqual(payload["components"], [])
        self.assertEqual(payload["evidence"], [])
        self.assertNotIn("features", payload)
        self.assertNotIn("sequence", json.dumps(payload).lower())

    def test_component_requires_admitted_evidence(self):
        with self.assertRaisesRegex(ValueError, "missing evidence"):
            new_host_state(
                profile(),
                host_state_id="host-state-001",
                as_of=T1,
                components=(component("missing"),),
                evidence=(),
                created_at=T1,
            )

    def test_evidence_for_other_host_is_refused(self):
        wrong = evidence(host_profile_id="other:v1")
        with self.assertRaisesRegex(ValueError, "must match the snapshot host"):
            new_host_state(
                profile(),
                host_state_id="host-state-001",
                as_of=T1,
                components=(component(wrong.evidence_id),),
                evidence=(wrong,),
                created_at=T1,
            )

    def test_future_evidence_cannot_leak_into_earlier_state(self):
        future = evidence(observed_at=T2)
        with self.assertRaisesRegex(ValueError, "observed after"):
            new_host_state(
                profile(),
                host_state_id="host-state-001",
                as_of=T1,
                components=(component(),),
                evidence=(future,),
                created_at=T2,
            )

    def test_state_component_domain_and_basis_are_bounded(self):
        payload = component().to_dict()
        payload["domain"] = "made_up_domain"
        with self.assertRaisesRegex(ValueError, "state domain"):
            host_state_component_from_dict(payload)

        payload = component().to_dict()
        payload["basis"] = "truth"
        with self.assertRaisesRegex(ValueError, "component basis"):
            host_state_component_from_dict(payload)

    def test_new_snapshot_references_but_does_not_inherit_previous_components(self):
        p = profile()
        first = new_host_state(
            p,
            host_state_id="host-state-001",
            as_of=T1,
            components=(component(),),
            evidence=(evidence(),),
            created_at=T1,
        )
        second = new_host_state(
            p,
            host_state_id="host-state-001",
            revision=2,
            as_of=T2,
            previous_state=first,
            limitations=("No current dynamic components have been admitted.",),
            created_at=T2,
        )

        self.assertEqual(second.components, ())
        self.assertEqual(second.evidence, ())
        self.assertEqual(second.previous_state.record_id, first.record_id)
        self.assertEqual(
            second.previous_state.content_sha256,
            first.content_sha256,
        )

    def test_previous_state_must_be_same_host_and_not_from_future(self):
        wrong_host = HostStateReference(
            record_id="other-state:v1",
            content_sha256="c" * 64,
            host_profile_id="other:v1",
            host_genome_sha256=DIGEST,
            as_of=T0,
        )
        with self.assertRaisesRegex(ValueError, "host_profile_id"):
            new_host_state(
                profile(),
                host_state_id="host-state-001",
                as_of=T1,
                previous_state=wrong_host,
                created_at=T1,
            )

        future = HostStateReference(
            record_id="host-state-001:v1",
            content_sha256="c" * 64,
            host_profile_id="isolate-001:v1",
            host_genome_sha256=DIGEST,
            as_of=T2,
        )
        with self.assertRaisesRegex(ValueError, "cannot be later"):
            new_host_state(
                profile(),
                host_state_id="host-state-001",
                revision=2,
                as_of=T1,
                previous_state=future,
                created_at=T2,
            )

    def test_reference_round_trip_and_lookup(self):
        p = profile()
        state = new_host_state(
            p,
            host_state_id="host-state-001",
            as_of=T1,
            components=(component(),),
            evidence=(evidence(),),
            created_at=T1,
        )
        reference = host_state_reference(state)
        self.assertEqual(reference.record_id, state.record_id)
        self.assertEqual(
            state.component(
                "phenotype_history",
                "growth_response_to_prior_phage",
            ),
            component(),
        )

    def test_content_hash_detects_tampering(self):
        state = new_host_state(
            profile(),
            host_state_id="host-state-001",
            as_of=T1,
            components=(component(),),
            evidence=(evidence(),),
            created_at=T1,
        )
        payload = state.to_dict()
        rebuilt = host_state_from_dict(payload)
        self.assertEqual(rebuilt.content_sha256, state.content_sha256)

        tampered = json.loads(json.dumps(payload))
        tampered["components"][0]["value"] = "positive"
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            host_state_from_dict(tampered)

    def test_file_round_trip(self):
        state = new_host_state(
            profile(),
            host_state_id="host-state-001",
            as_of=T1,
            components=(component(),),
            evidence=(evidence(),),
            created_at=T1,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "host-state.json"
            write_host_state(state, path)
            loaded = load_host_state(path)
        self.assertEqual(loaded.to_dict(), state.to_dict())


class HostStateArtifactEvidenceTests(unittest.TestCase):
    def test_measurement_adapter_copies_lineage_without_interpreting_data(self):
        measurement = Measurement(
            measurement_id="measurement-001",
            revision=1,
            run_id="run-001",
            experiment_spec_id="experiment-001:v1",
            experiment_spec_sha256="d" * 64,
            experiment_arm_id="treatment",
            target_host_profile_id="isolate-001:v1",
            phage_profile_ids=("PH-001:v1",),
            source_step="measure",
            device_id="reader-001",
            material_batch_ids=("host-batch:v1", "phage-batch:v1"),
            origin="physical_run",
            physical_execution=True,
            qc_status="valid",
            qc_evidence=("qc-001",),
            measurement_type="device_result",
            data={"signal": [1.0, 2.0]},
            recorded_at=T1,
            created_at=T1,
        )
        ref = host_state_evidence_from_measurement(
            measurement,
            evidence_id="measurement-evidence",
            relation="supports a time-dependent state variable",
        )
        self.assertEqual(ref.reference_id, measurement.record_id)
        self.assertEqual(ref.reference_sha256, measurement.content_sha256)
        self.assertEqual(ref.host_profile_id, "isolate-001:v1")
        self.assertNotIn("signal", ref.details)

    def test_phenotype_adapter_preserves_exact_interpretation_artifact_hash(self):
        phenotype = Phenotype(
            phenotype_id="phenotype-001",
            revision=1,
            experiment_spec_id="experiment-001:v1",
            experiment_spec_sha256="d" * 64,
            experiment_arm_id="treatment",
            target_host_profile_id="isolate-001:v1",
            phage_profile_ids=("PH-001:v1",),
            material_batch_ids=("host-batch:v1", "phage-batch:v1"),
            measurement_ids=("measurement-001:v1",),
            phenotype_type="growth_response",
            outcome="graded",
            value=0.5,
            unit="assessor_units",
            interpretation="Explicit admitted phenotype.",
            assessor=PhenotypeAssessor(name="manual", version="1"),
            assessed_at=T1,
        )
        ref = host_state_evidence_from_phenotype(
            phenotype,
            evidence_id="phenotype-evidence",
            relation="records historical phenotype at H(t)",
        )
        self.assertEqual(ref.kind, "phenotype")
        self.assertEqual(ref.reference_id, phenotype.record_id)
        self.assertEqual(ref.reference_sha256, phenotype.content_sha256)
        self.assertEqual(ref.observed_at, phenotype.assessed_at)



class HostStateCliTests(unittest.TestCase):
    def test_cli_creates_evidence_backed_host_state(self):
        from phage_lab.__main__ import main

        p = profile()
        state_input = {
            "components": [component().to_dict()],
            "evidence": [evidence().to_dict()],
            "limitations": [
                "This snapshot includes only explicitly supplied dynamic state."
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile_path = root / "host-profile.json"
            input_path = root / "state-input.json"
            out = root / "host-state.json"
            write_host_profile(p, profile_path)
            input_path.write_text(json.dumps(state_input), encoding="utf-8")

            self.assertEqual(
                0,
                main([
                    "host-state",
                    "--host-profile", str(profile_path),
                    "--host-state-id", "host-state-cli",
                    "--as-of", T1,
                    "--state-input", str(input_path),
                    "--out", str(out),
                ]),
            )
            loaded = load_host_state(out)
            self.assertEqual(loaded.record_id, "host-state-cli:v1")
            self.assertEqual(len(loaded.components), 1)
            self.assertEqual(len(loaded.evidence), 1)

    def test_cli_can_link_previous_snapshot_without_inheriting_it(self):
        from phage_lab.__main__ import main

        p = profile()
        previous = new_host_state(
            p,
            host_state_id="host-state-cli",
            as_of=T1,
            components=(component(),),
            evidence=(evidence(),),
            created_at=T1,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile_path = root / "host-profile.json"
            previous_path = root / "previous.json"
            out = root / "next.json"
            write_host_profile(p, profile_path)
            write_host_state(previous, previous_path)

            self.assertEqual(
                0,
                main([
                    "host-state",
                    "--host-profile", str(profile_path),
                    "--host-state-id", "host-state-cli",
                    "--host-state-revision", "2",
                    "--as-of", T2,
                    "--previous-host-state", str(previous_path),
                    "--out", str(out),
                ]),
            )
            loaded = load_host_state(out)
            self.assertEqual(loaded.components, ())
            self.assertEqual(loaded.previous_state.record_id, previous.record_id)


if __name__ == "__main__":
    unittest.main()
