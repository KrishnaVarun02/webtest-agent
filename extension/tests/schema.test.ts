import assert from "node:assert/strict";
import { describe, it } from "node:test";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import recordingSchema from "../schema/recording.v1.schema.json";
import sampleRecording from "../../scripts/fixtures/sample-recording.json";

describe("versioned recording schema", () => {
  it("is a valid draft-2020 schema and accepts the shared end-to-end recording fixture", () => {
    const ajv = new Ajv2020({ allErrors: true, strict: true });
    addFormats(ajv);
    const validate = ajv.compile(recordingSchema);
    const valid = validate(sampleRecording);
    assert.equal(valid, true, ajv.errorsText(validate.errors, { separator: "\n" }));
  });

  it("rejects an unversioned or unexpectedly shaped recording", () => {
    const ajv = new Ajv2020({ allErrors: true, strict: true });
    addFormats(ajv);
    const validate = ajv.compile(recordingSchema);
    assert.equal(validate({ ...sampleRecording, schemaVersion: "2", unexpected: true }), false);
  });
});
