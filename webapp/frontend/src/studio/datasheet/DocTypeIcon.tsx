import {
  Boxes,
  FileText,
  GitBranch,
  GitMerge,
  GitPullRequest,
  List,
  ListChecks,
  Repeat,
  ScrollText,
  Tag,
} from "lucide-react";

const MAP: Record<string, typeof FileText> = {
  "file-text": FileText,
  "list-checks": ListChecks,
  "scroll-text": ScrollText,
  "git-merge": GitMerge,
  list: List,
  "git-pull-request": GitPullRequest,
  "git-branch": GitBranch,
  boxes: Boxes,
  repeat: Repeat,
  tag: Tag,
};

export default function DocTypeIcon({ name, size = 14 }: { name: string; size?: number }) {
  const Cmp = MAP[name] || FileText;
  return <Cmp size={size} strokeWidth={1.6} />;
}
