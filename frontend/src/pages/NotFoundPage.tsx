import { Link } from "react-router-dom";
import EmptyState from "../components/EmptyState";

export default function NotFoundPage() {
  return (
    <EmptyState
      heading="page not found"
      body="the page you're looking for doesn't exist."
      action={<Link to="/">back home</Link>}
    />
  );
}
