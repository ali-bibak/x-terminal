<script lang="ts">
  import { Plus, X } from "lucide-svelte";
  import { clickOutside } from "$lib/actions/clickOutside";
  import api from "$lib/api";

  interface Props {
    isOpen?: boolean;
    onClose?: () => void;
  }

  let { isOpen = $bindable(false), onClose }: Props = $props();

  let label = $state("");

  async function handleCreate() {
    if (label.trim()) {
      await api.createTopic({
        label: label.trim(),
        query: label.trim(),
        resolution: "1m",
      });

      label = "";
      isOpen = false;
    }
  }

  function handleClose() {
    label = "";
    isOpen = false;
    onClose?.();
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      handleCreate();
    } else if (e.key === "Escape") {
      handleClose();
    }
  }
</script>

{#if isOpen}
  <div class="fixed inset-0 z-50 flex items-start justify-center pt-20">
    <!-- Backdrop -->
    <div class="fixed inset-0 bg-black/50" onclick={handleClose}></div>

    <!-- Popover -->
    <div
      class="relative bg-stone-950 border border-stone-800 rounded-xl p-6 w-full max-w-md shadow-xl"
      use:clickOutside={handleClose}
    >
      <!-- Header -->
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-xl font-bold">Create New Topic</h2>
        <button
          onclick={handleClose}
          class="text-stone-400 hover:text-white hover:bg-stone-800 rounded-full p-1"
        >
          <X size={20} />
        </button>
      </div>

      <!-- Form -->
      <div class="space-y-4">
        <div>
          <label
            for="topic-label"
            class="block text-sm font-medium text-stone-400 mb-2"
          >
            Topic Label
          </label>
          <input
            id="topic-label"
            type="text"
            bind:value={label}
            onkeydown={handleKeydown}
            placeholder="e.g., $TSLA or California Earthquake"
            class="w-full px-4 py-2 bg-black border border-stone-800 rounded-full focus:outline-none focus:border-blue-400 border-2 text-white"
            autofocus
          />
        </div>

        <!-- Actions -->
        <div class="flex gap-2 pt-2">
          <button
            onclick={handleClose}
            class="flex-1 px-4 py-2 border border-stone-800 rounded-full hover:bg-stone-800 font-medium"
          >
            Cancel
          </button>
          <button
            onclick={handleCreate}
            disabled={!label.trim()}
            class="flex-1 px-4 py-2 bg-blue-400 hover:bg-blue-400/80 disabled:bg-stone-800 disabled:text-stone-500 disabled:cursor-not-allowed rounded-full font-medium"
          >
            Create
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
