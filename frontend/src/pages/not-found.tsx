import { CompassIcon } from "lucide-react";
import { Link } from "react-router";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";

export default function NotFoundPage() {
  return (
    <EmptyState
      icon={CompassIcon}
      title="این صفحه وجود ندارد"
      action={
        <Button asChild>
          <Link to="/">نمای کلی</Link>
        </Button>
      }
    />
  );
}
