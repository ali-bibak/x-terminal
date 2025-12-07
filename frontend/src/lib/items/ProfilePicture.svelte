<script lang="ts">
  interface Props {
    size?: number;
  }

  let { size = 48 }: Props = $props();
</script>

<img
  src="https://picsum.photos/{size}/{size}?random={Math.random()}"
  alt="Profile"
  class="rounded-full"
  width={size}
  height={size}
/>
