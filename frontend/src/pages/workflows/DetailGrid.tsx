import { Fragment } from "react";
import { KindDef, WorkflowRecord } from "../../api/types";
import FieldRenderer from "../../components/FieldRenderer";
import styles from "./workflows.module.css";

// Parity workflow.js detailGrid: detail_fields ?? every declared field, label/value pairs.
export default function DetailGrid({ kind, record }: { kind: KindDef; record: WorkflowRecord }) {
  const names = kind.detail_fields ?? Object.keys(kind.fields);
  return (
    <div className={styles.detailGrid}>
      {names.map((name) => (
        <Fragment key={name}>
          <label>{name.replace(/_/g, " ")}</label>
          <FieldRenderer field={kind.fields[name]} value={record[name]} mode="detail" record={record} />
        </Fragment>
      ))}
    </div>
  );
}
