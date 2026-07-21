import Button from "../../components/Button";
import EmptyState from "../../components/EmptyState";

export default function ResourcesEmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <EmptyState
      heading="no resources yet"
      body="resources give your agent durable reference material such as profiles, notes, datasets, and instructions."
      action={
        <Button variant="primary" onClick={onCreate}>
          Create resource
        </Button>
      }
    />
  );
}
