import { useEffect, useState } from "react";
import Button from "../components/Button";
import EmptyState from "../components/EmptyState";
import { useApproveSkill, useSaveSkill, useSkill, useSkills } from "../api/queries/skills";
import SmartTextarea from "../components/SmartTextarea";
import styles from "./SkillsPage.module.css";

export default function SkillsPage() {
  const { data: skills = [] } = useSkills();
  const approve = useApproveSkill();
  const [selected, setSelected] = useState<string | null>(null);
  const { data: detail } = useSkill(selected ?? "");
  const save = useSaveSkill(selected ?? "");
  const [draft, setDraft] = useState("");
  useEffect(() => { if (detail) setDraft(detail.text); }, [detail]);

  if (skills.length === 0) {
    return <EmptyState heading="no skills registered" body="skills seed from the repo at startup" />;
  }

  return (
    <>
      <div className={styles.grid}>
        {skills.map((skill) => (
          <article key={skill.name} className={styles.card}>
            <div className={styles.head}>
              <strong className={styles.name}>{skill.name}</strong>
              <span className={styles.meta}>[{skill.status} · {skill.source}]</span>
            </div>
            <p className={styles.desc}>{skill.description}</p>
            <div className={styles.actions}>
              {skill.status === "pending" && (
                <Button onClick={() => approve.mutate(skill.name)}>Approve</Button>
              )}
              <Button variant="ghost" onClick={() => { setSelected(skill.name); setDraft(""); }}>Edit guidance</Button>
            </div>
          </article>
        ))}
      </div>
      {selected && detail && <section className={styles.editor}><h2>{selected}</h2><p>Skills are progressively loaded instruction packages; workflows and agents execute them.</p><SmartTextarea value={draft || detail.text} onChange={setDraft} aria-label="skill manifest" /><Button variant="primary" onClick={() => save.mutate(draft || detail.text)}>Save skill</Button></section>}
    </>
  );
}
