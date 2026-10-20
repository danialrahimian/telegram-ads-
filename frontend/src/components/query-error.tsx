import { AlertCircleIcon, RotateCwIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api";

export function QueryError({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <Alert variant="destructive">
      <AlertCircleIcon />
      <AlertTitle>بارگذاری نشد</AlertTitle>
      <AlertDescription>
        <p>{errorMessage(error)}</p>
        {retry && (
          <Button size="sm" variant="outline" className="mt-2" onClick={retry}>
            <RotateCwIcon /> تلاش دوباره
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}
