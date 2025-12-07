<script lang="ts">
  import type { FactCheckStatus } from "$lib/types";
  import { Check, X } from "lucide-svelte";

  interface Props {
    timestamp?: string;
    content: string;
    isLast?: boolean;
    factCheckedByGrok?: FactCheckStatus;
  }

  let {
    timestamp = "Just now",
    content,
    isLast = false,
    factCheckedByGrok = "CHECKED",
  }: Props = $props();
</script>

<div class="flex gap-x-4">
  <div class="flex flex-col items-center">
    <div class="w-2 h-2 rounded-full bg-white mt-2"></div>
    {#if !isLast}
      <div
        class="w-0.5 flex-1 min-h-16 bg-linear-to-b from-stone-700 via-stone-700 to-stone-700/40"
      ></div>
    {/if}
  </div>

  <div class="flex-1">
    <p class="text-stone-400 text-sm mb-1">{timestamp}</p>
    <p>{content}</p>
    {#if true}
      <div class="text-red-400 text-sm mb-1 flex flex-row items-center">
        <X class="h-4" />
        Deemed false by Grok: Some explanation
      </div>
    {:else}
      <div class="text-stone-400 text-sm mb-1 flex flex-row items-center">
        <Check class="h-4" />
        Fact checked by Grok
      </div>
    {/if}
  </div>
</div>
