r""".. role:: html(raw)
   :format: html

JIT compilation of Shor's algorithm with PennyLane and Catalyst
===============================================================

.. meta::
    :property="og:description": JIT compile Shor's algorithm from end-to-end.

    :property="og:image": https://pennylane.ai/qml/_static/demonstration_assets//fano.png

.. related::

    tutorial_iterative_quantum_phase_estimation IPE demo (update when available)

*Author: Olivia Di Matteo — Posted: X Y 2024. Last updated: X Y 2024.*
"""

##############################################################################
# The past few years stimulated a lot of discussion about *hybrid
# quantum-classical algorithms*. For a time, this terminology was synonymous
# with *variational algorithms*. However, integration with classical
# co-processors is necessary for every quantum algorithm, even ones considered
# quintessentially quantum. 
#
# Shor's famous factoring algorith [CITE] is one such example. Have a look at the
# example code below:

import jax.numpy as jnp

def shors_algorithm(N):
    p, q = 0, 0

    while p * q != N:
        a = jnp.random.choice(jnp.arange(2, N - 1))

        if jnp.gcd(N, a) != 1:
            p = jnp.gcd(N, a)
            return p, N // p

        guess_r = guess_order(N, a)

        if guess_r % 2 == 0:
            guess_square_root = (a ** (guess_r // 2)) % N

            # Ensure the guessed solution is non-trivial
            if guess_square_root not in [1, N - 1]:
                p = jnp.gcd(N, guess_square_root - 1)
                q = jnp.gcd(N, guess_square_root + 1)

    return p, q

######################################################################
# If you saw this code out-of-context, would you even realize this is a quantum
# algorithm? There are no quantum circuits in sight!
#
# As quantum hardware continues to scale up, the way we think about quantum
# programming is evolving in tandem. Writing circuits gate-by-gate for
# algorithms with hundreds or thousands of qubits is unsustainable. Morever, a
# programmer doesn't actually need to know anything quantum is happening, if the
# software library can generate and compile appropriate quantum code (though,
# they should probably have at least some awareness, since the output of
# ``guess_order`` is probabilistic!).  This raises some questions: what gets
# compiled, where and how does compilation happen, and what do we gain?
#
# Over the past year, PennyLane has become increasingly integrated with
# `Catalyst
# <https://docs.pennylane.ai/projects/catalyst/en/latest/index.html>`_, which
# for just-in-time compilation of classical and quantum code together. In this
# demo, we will leverage this to develop an implementation of Shor's factoring
# algorithm that is just-in-time compiled from end-to-end, classical control
# structure and all. In particular, we will see how to leverage Catalyst's
# mid-circuit measurement capabilities to reduce the size of quantum circuits,
# and how JIT compilation enables faster execution overall.
#
# Crash course on Shor's algorithm
# --------------------------------
#
# Looking back at the code above, we can see that Shor's algorithm is broken
# down into a couple distinct steps. Suppose we wish to decompose an integer
# :math:`N` into its two constituent prime factors, :math:`p` and :math:`q`.
#
#  - First, we randomly select a candidate integer, :math:`a`, between 2 and
#    :math:`N-1` (before proceeding, we double check that we did not get lucky and randomly select one of the true factors)
#  - Using our chosen a, we proceed to the quantum part of the algorithm: order-finding.
#    Quantum circuits are generated, and the circuit is executed on a device. The results
#    are used to make a guess for a non-trivial square root.
#  - If the square root is non-trivial, we test whether we found the factors. Otherwise, we try again
#    with more shots. Eventually, we try with a different value of a.
#    
# For a full description of Shor's algorithm, the interested reader is referred
# to the relevant module in the `PennyLane Codebook
# <https://pennylane.ai/codebook/10-shors-algorithm/>`_. What's important here
# for us is to note that for each new value of :math:`a` (and more generally,
# each possible :math:`N`), we must compile and optimize many large quantum
# circuits, each of which consists of many nested subroutines.
#
# In both classical and quantum programming, compilation is the process of
# translating operations expressed in high-level languages down to the language
# of the hardware. As depicted below, it involves multiple passes over the code,
# through one or more intermediate representations, and both machine-independent and
# dependent optimizations.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/compilation-stack.svg
#    :scale: 75%
#    :align: center
#    :alt: The quantum compilation stack.
#
#    High-level overview of the quantum compilation stack and its constituent
#    parts. Each step contains numerous subroutines and passes of its own, and
#    many require solving computationally hard problems (or very good heuristic
#    techniques).
#
# Developing automated compilation tools is a very active and important area of
# research, and is a major requirement for today's software stacks. Even if a
# library contains many functions for pre-written quantum circuits, without a
# proper compiler a user would be left to optimize and map them to hardware by hand.
# This is an extremely laborious (and error-prone!) process, and furthermore,
# is unlikely to be optimal.
#
# However, our implementation of Shor's algorithm surfaces another complication.
# Even if we have a good compiler, every random choice of ``a`` yields a
# different quantum circuit (as we will discuss in the implementation details
# below). Each of these circuits, generated independently at runtime, would need
# to be compiled and optimized, leading to a huge overhead in computation
# time. One could potentially generate, optimize, and store circuits and
# subroutines for reuse. But note that they depend on both ``a`` and ``N``,
# where in a cryptographic context, ``N`` relates to a public key which is
# unique for every entity. Morever, for sizes of cryptographic relevance, ``N``
# will be a 2048-bit integer or larger!
#
# The previous discussion also neglects the fact that the quantum computation
# happens within the context of an algorithm that includes classical code and
# control flow. In Shor's algorithm, this is fairly minimal, but one can imagine
# larger workflows with substantial classical subroutines that themselves must
# be compiled and optimized, perhaps even in tandem with the quantum code. This
# is where Catalyst and quantum just-in-time compilation come into play.
#
#
# JIT compiling classical and quantum code
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#
# In *compiled* languages, like C and C++, compilation is a process that happens
# offline prior to executing your code. An input program is sent to a compiler,
# which outputs a new program in assembly code. An assembler then turns this
# into a machine-executable program which you can run and feed inputs
# to. [#PurpleDragonBook]_.
#
# On the other hand, in *interpreted* languages (like Python), both the source
# program and inputs are fed to the interpreter, which processes them line
# by line, and directly gives us the program output.
# 
# Compiled and interpreted languages, and languages within each category, all
# have unique strengths and weakness. Compilation will generally lead to faster
# execution, but can be harder to debug than interpretation, where execution can
# halt partway and provide direct diagnostic information about where something
# went wrong [#PurpleDragonBook]_. *Just-in-time compilation* offers a solution
# that lies, in some sense, at the boundary between the two.
#
# Just-in-time compilation involves compiling code *during* execution, for instance,
# while an interpreter is doing its job. 
#

######################################################################
# The quantum part
# ^^^^^^^^^^^^^^^^
#
# In this section we describe the circuits that make up the quantum subroutine
# in Shor's algorithm, i.e., the order-finding routine. The presented
# implementation is based on [#Beauregard2003]_. For an integer :math:`N` with
# an :math:`n = \lceil \log_2 N \rceil`-bit representation, the circuit requires
# :math:`2n + 3` qubits. Of these, :math:`n + 1` are for computation and
# :math:`n + 2` are auxiliary.
#
# Order finding is an application of *quantum phase estimation*. We wish to 
# estimate the phase, :math:`theta`, of the operator :math:`U_a`,
#
# .. math::
#
#     U_a \vert x \rangle = \vert ax \pmod N \rangle
#
# where the :math:`\vert x \rangle` is the binary representation of integer
# :math:`x`, and :math:`a` is the randomly-generated integer discussed
# above. The full QPE circuit, using :math:`t` estimation wires, is presented
# below.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/qpe_full.svg
#    :width: 600
#    :align: center
#    :alt: Quantum phase estimation circuit for order finding.
#
# This high-level view of the circuit hides its complexity, given that the
# implementation details of :math:`U_a` are not shown and auxiliary qubits are
# omitted. In what follows, we'll leverage shortcuts afforded by the hybrid
# nature of computation, and from Catalyst. Specifically, with mid-circuit
# measurement and reset we can reduce the number of estimation wires to
# :math:`t=1`. Most of the required arithmetic will be performed in the Fourier
# basis. Since we know :math:`a` in advance, we can vary circuit structure on
# the fly and save resources. Finally, additional mid-circuit measurements can
# be used in lieu of uncomputation.
#
# First, we'll use our knowledge of classical parameters to simplify the
# implementation of the controlled :math:`U_a^{2^k}`. Naively, it looks like we
# must apply a controlled :math:`U_a` operation :math:`2^k` times. However, note
#
# .. math::
#
#     U_a^{2^k}\vert x \rangle = \vert (a \cdot a \cdots a) x \pmod N \rangle = \vert a^{2^k}x \pmod N \rangle = U_{a^{2^k}} \vert x \rangle
#
# Since :math:`a` is known in advance, we can classically evaluate
# :math:`a^{2^k}` and implement controlled-:math:`U_{a^{2^k}}` instead.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/qpe_full_modified_power.svg
#    :width: 600
#    :align: center
#    :alt: Order finding with controlled operations that take advantage of classical precomputation.
#
# There is a tradeoff here: since each controlled operation is now different, we
# will have to optimize each circuit separately during compilation. However,
# additional compilation time could be outweighed by the fact that we must now
# run only :math:`t` controlled operations, instead of :math:`1 + 2 + 4 + \cdots
# + 2^{t-1} = 2^t - 1`. Later we'll also jit-compile the circuit construction.
#
# Next, let's zoom in on an arbitrary controlled-:math:`U_a`. 
# 
# .. figure:: ../_static/demonstration_assets/shor_catalyst/c-ua.svg
#    :width: 700
#    :align: center
#    :alt: Quantum phase estimation circuit for order finding.
#
# The control qubit, :math:`\vert c\rangle`, is an estimation qubit. The
# register :math:`\vert x \rangle` and the auxiliary register contain :math:`n`
# and :math:`n + 1` qubits respectively, for reasons we elaborate on below.
#
# :math:`M_a` multiplies the contents of one register by :math:`a` and adds it to
# another register, in place and modulo :math:`N`,
# 
# .. math::
#
#     M_a \vert x \rangle \vert b \rangle \vert 0 \rangle =  \vert x \rangle \vert (b + ax) \pmod N \rangle \vert 0 \rangle.
#
# Ignoring the control qubit, let's validate that this circuit implements
# :math:`U_a`:
#
# .. math::
#
#     \begin{eqnarray}
#       M_a \vert x \rangle \vert 0 \rangle^{\otimes n + 1} \vert 0 \rangle &=&  \vert x \rangle \vert ax \rangle \vert 0 \rangle \\
#      SWAP (\vert x \rangle \vert ax \rangle ) \vert 0 \rangle &=&  \vert ax \rangle \vert x \rangle \vert 0 \rangle \\
#     M_{a^{-1}}^\dagger \vert ax \rangle \vert x \rangle  \vert 0 \rangle &=& \vert ax\rangle \vert x - a^{-1}(ax) \rangle \vert 0 \rangle \\
#      &=& \vert ax \rangle \vert 0 \rangle^{\otimes n + 1} \vert 0 \rangle,
#     \end{eqnarray}
#
# where we've omitted the "mod :math:`N`" for readability, and used the fact
# that the adjoint of addition is subtraction.
#
# A high-level implementation of a controled :math:`M_a` is shown below.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/doubly-controlled-adder-with-control.svg
#    :width: 700 
#    :align: center
#    :alt: Doubly-controlled adder.
#
# First, note that the controls on the QFTs are not needed. If we were to remove
# them, and :math:`\vert c \rangle = \vert 1 \rangle`, the circuit will work as
# expected. If instead :math:`\vert c \rangle = \vert 0 \rangle`, they would
# run, then cancel each other out, since none of the interior operations would
# execute (note that this optimization is broadly applicable, and quite
# useful!). We are left, then, with the circuit below.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/doubly-controlled-adder-with-control-not-on-qft.svg
#    :width: 700 
#    :align: center
#    :alt: Doubly-controlled adder.
#
# At first glance, it may not be clear how :math:`a x` is created. The qubits in
# register :math:`\vert x \rangle` are controlling operations that depend on
# :math:`a` multiplied by various powers of 2. There is also a QFT before and
# after, whose purpose is unclear.
#
# These special operations are actually performing *addition in the Fourier
# basis* [#Draper2000]_. This is another trick we can leverage, given prior
# knowledge of :math:`a`. Rather than performing explicit addition on bits in
# computational basis states, we can apply a Fourier transform, adjust the
# phases based on the bits in the number we wish to add, then inverse Fourier
# transform to obtain the result. We present the circuit for the *Fourier
# adder*, :math:`\Phi`, below.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/fourier_adder.svg
#    :width: 500 
#    :align: center
#    :alt: Addition in the Fourier basis.
#
# The :math:`\mathbf{R}_k` are phase shifts, to be described below. To see how
# this works, let's first take a closer look at the QFT. The qubit ordering in
# the circuit is such that for an :math:`n`-bit integer :math:`b`, :math:`\vert
# b\rangle = \vert b_{n-1} \cdots b_0\rangle` and :math:`b = \sum_{k=0}^{n-1}
# 2^k b_k`.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/fourier_adder_explanation-1.svg 
#    :width: 800 
#    :align: center
#    :alt: The Quantum Fourier Transform.
#
# where
#
# .. math::
#
#     R_k = \begin{pmatrix} 1 & 0 \\ 0 & e^{\frac{2\pi i}{2^k}} \end{pmatrix}.
#
# Let's add a new register, prepared in the basis state :math:`\vert a \rangle`.
# In the next circuit, we control on qubits in :math:`\vert a \rangle` to modify
# the phases in :math:`\vert b \rangle` (after a QFT is applied) in a very
# particular way:
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/fourier_adder_explanation-2.svg 
#    :width: 800 
#    :align: center
#    :alt: Adding one integer to another with the Quantum Fourier Transform.
#
# We observe each qubit in :math:`\vert b \rangle` icks up a phase that depends
# on the bits in :math:`a`. In particular, bit :math:`b_k` accumulates
# information about all the bits in :math:`a` with an equal or lower index,
# :math:`a_0, \ldots, a_{k}`. The effect is that of adding :math:`a_k` to
# :math:`b_k`; looking across the entire register, we are adding :math:`a` to
# :math:`b`, up to an inverse Fourier transform!
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/fourier_adder_explanation-3.svg 
#    :width: 800 
#    :align: center
#    :alt: Adding one integer to another with the Quantum Fourier Transform.
#
# However, we must be careful. Fourier basis addition is *not* automatically
# modulo :math:`N`. If the sum :math:`b + a` requires :math:`n+ 1` bits, it will
# overflow. To handle that, one extra qubit is added to the top of the
# :math:`\vert b\rangle` register (initialized to :math:`\vert 0 \rangle`). This
# is the source of one of the auxiliary qubits mentioned earlier.
#
# Now, note that we don't actually need a second register of qubits in our
# case. Since we know :math:`a` in advance, we can precompute the amount of
# phase to apply: on qubit :math:`\vert b_k \rangle`, we must rotate by
# :math:`\sum_{\ell=0}^{k} \frac{a_\ell}{2^{\ell+1}}`. We'll express this as a
# new gate,
#
# .. math::
#
#     \mathbf{R}_k = \begin{pmatrix} 1 & 0 \\ 0 & e^{2\pi i\sum_{\ell=0}^{k} \frac{a_\ell}{2^{\ell+1}}} \end{pmatrix}.
#
# The final circuit for the Fourier adder is
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/fourier_adder_explanation-4.svg 
#    :width: 500 
#    :align: center
#    :alt: Full Fourier adder.
#
# As one may expect, :math:`\Phi^\dagger` performs subtraction. However, we must
# also consider the possibility of underflow.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/fourier_adder_adjoint.svg 
#    :width: 350 
#    :align: center
#    :alt: Subtraction in the Fourier basis.
#
# Returning to :math:`M_a`, we have :math:`\Phi_+` which is similar to
# :math:`\Phi`, but it (a) uses an auxiliary qubit, and (b) works modulo
# :math:`N`. :math:`\Phi_+` still uses Fourier basis addition and subtraction,
# but also applies corrections if overflow is detected. Let's consider a single
# instance of a controlled :math:`\Phi_+(a)`, sandwiched between a QFT and
# inverse QFT.  
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/fourier_adder_modulo_n.svg
#    :width: 800 
#    :align: center
#    :alt: Addition in the Fourier basis modulo N.
#
# Here we've applied the same tricks to remove controls on the internal QFT
# and inverse QFT operations.
#
# Let's step through this circuit, assuming the control qubit is in :math:`\vert
# 1 \rangle` (if it was :math:`\vert 0 \rangle`, only the QFTs are applied, and
# they cancel out). First, we add :math:`a` to :math:`b`, then subtract
# :math:`N`. If :math:`a + b \geq N`, this gives us the correct result modulo
# :math:`N`, and the topmost qubit is in state 0. The CNOT down to the auxiliary
# qubit does not trigger.  We then subtract :math:`a`; this will cause
# underflow, leading to the topmost qubit being in state :math:`\vert 1
# \rangle`. The controlled-on-0 CNOT does not trigger either, and we simply add
# :math:`a` back.
# 
# However, if :math:`a + b < N` we subtracted :math:`N` for no reason, causing
# underflow. The top-most qubit will be in :math:`\vert 1 \rangle` (recall we
# added that qubit to :math:`\Phi` to account for precisely this; note too that
# we must exit the Fourier basis to detect underflow). We flip the auxiliary
# qubit, and perform controlled addition of :math:`N`. The remainder of the
# circuit returns the auxiliary qubit to its original state. If there was
# originally underflow, we subtract :math:`a` and there is now no underflow, so
# the auxiliary qubit is returned to :math:`\vert 0 \rangle`.
#
# We can use similar tricks to remove additional pairs of controls, denoted by
# colours in the circuit below.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/fourier_adder_modulo_n-less-controls-coloured.svg
#    :width: 800 
#    :align: center
#    :alt: Addition in the Fourier basis modulo N.
#
# This leaves us with the following circuit.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/fourier_adder_modulo_n-less-controls.svg
#    :width: 800 
#    :align: center
#    :alt: Addition in the Fourier basis modulo N.
#
# We can see here that uncomputing the auxiliary qubit is just as much work as
# performing the operation itself! Thankfully, we can leverage Catalyst to
# perform a major optimization: rather than uncomputing, simply measure the
# auxiliary qubit, add back :math:`N` based on the classical outcome, then reset
# it to :math:`\vert 0 \rangle`!
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/fourier_adder_modulo_n_mcm.svg
#    :scale: 120%
#    :align: center
#    :alt: Addition in the Fourier basis modulo N.
#
# This optimization cuts down the number of gates in :math:`M_a` by essentially
# half, which is a major savings. All the same optimizations can be made in the
# case above, too, where this entire operation is controlled on an additional
# qubit, :math:`\vert c \rangle`.
#
# Recall that :math:`\Phi_+` is used as part of :math:`M_a` to add
# :math:`2^{k}a` modulo :math:`N` to :math:`b` (conditioned on the value of
# :math:`x_{k}`) in the Fourier basis. Re-expressing this as a sum (all
# modulo :math:`N`), we find
#
# .. math::
#
#     \begin{equation*}
#     b + x_{0} \cdot 2^0 a + x_{1} \cdot 2^1 a + \cdots x_{n-1} \cdot 2^{n-1} a  = b + a \sum_{k=0}^{n-1} x_{k} 2^k =  b + a x.
#     \end{equation*}
#
# This completes our implementation of the controlled-:math:`U_{a^{2^k}}`. The
# current qubit count is :math:`t + 2n + 2`. There is one major optimization
# left: reducing the number of estimation qubits. A higher :math:`t` gives a
# more accurate estimate of phase, but adds overhead in both circuit depth, and
# classical simulation memory and time. Below we show how the :math:`t` can be
# reduced to 1 without compromising precision or classical memory, and with
# comparable circuit depth.
#
# Let's return to the QPE routine and expand the final inverse QFT.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/qpe_full_modified_power_with_qft.svg
#    :width: 800
#    :align: center
#    :alt: QPE circuit with inverse QFT expanded.
#
# Look carefully at the qubit in :math:`\vert \theta_0\rangle`. After the final
# Hadamard, it is used only for controlled gates. Thus, we can just measure it
# and apply subsequent operations controlled on the classical outcome,
# :math:`\theta_0`.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/qpe_full_modified_power_with_qft-2.svg
#    :width: 800
#    :align: center
#    :alt: QPE circuit with inverse QFT expanded and last estimation qubit measured off.
#
# Once again, we can do better by dynamically modifying the circuit based on
# classical information. Instead of applying controlled :math:`R^\dagger_2`, we
# can apply :math:`R^\dagger` where the rotation angle is 0 if :math:`\theta_0 =
# 0`, and :math:`\pi` if :math:`\theta_1`, i.e., :math:`R^\dagger_{2 \theta_0}`.
# The same can be done for all other gates controlled on :math:`\theta_0`.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/qpe_full_modified_power_with_qft-3.svg
#    :width: 800
#    :align: center
#    :alt: QPE circuit with inverse QFT expanded, last estimation qubit measured, and rotation gates adjusted.
#
# We'll leverage this trick again with the second-last estimation
# qubit. Moreover, we can make a further improvement by noting that once the
# last qubit is measured, we can reset and repurpose it to play the role of the
# second last qubit.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/qpe_full_modified_power_with_qft-4.svg
#    :width: 800
#    :align: center
#    :alt: QPE circuit with inverse QFT expanded and last estimation qubit reused.
#
# Once again, we adjust rotation angles based on measurement values, removing
# the need for classical controls.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/qpe_full_modified_power_with_qft-5.svg
#    :width: 800
#    :align: center
#    :alt: QPE circuit with inverse QFT expanded, last estimation qubit reused, and rotation gates adjusted.
#
# We can do this for all remaining estimation qubits, adding more rotations
# depending on previous measurement outcomes.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/qpe_full_modified_power_with_qft-6.svg
#    :width: 800
#    :align: center
#    :alt: QPE circuit with one estimation qubit, and unmerged rotation gates.
#
# Finally, since these are all :math:`RZ`, we can merge them. Let
#
# .. math::
#
#     \mathbf{M}_{k} = \begin{pmatrix} 1 & 0 \\ 0 & e^{-2\pi i\sum_{\ell=0}^{k}  \frac{\theta_{\ell}}{2^{k + 2 - \ell}}} \end{pmatrix}.
#
# With a bit of index gymnastics, we obtain our final QPE algorithm with a single estimation qubit:
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/qpe_full_modified_power_with_qft-7.svg
#    :width: 800
#    :align: center
#    :alt: QPE circuit with one estimation qubit.
#
# Replacing the controlled-:math:`U_a` with the subroutines derived above, we
# see Shor's algorithm requires :math:`2n + 3` qubits in total, as summarized in
# the graphic below.
#
# .. figure:: ../_static/demonstration_assets/shor_catalyst/qpe_full_combined.svg
#    :width: 800
#    :align: center
#    :alt: Full implementation of QPE circuit.
#
# TODO: insert code here


######################################################################
# JIT compilation and performance
# -------------------------------
# 
# TODO: show how everything gets put together and JITted
#
# TODO: discussions about technical details and challenges; autograph and
# control flow, dynamically-sized arrays, etc.
# 
# TODO: plots of performance 

# TODO: relevant code

######################################################################
# Conclusions
# -----------
# 
# TODO
#
# References
# ----------
#
# .. [#PurpleDragonBook]
#
#     Alfred V Aho, Monica S Lam, Ravi Sethi, Jeffrey D Ullman. (2007)
#     *Compilers Principles, Techniques, And Tools*. Pearson Education, Inc.
#
# .. [#Beauregard2003]
#
#     Stephane Beauregard. (2003) *Circuit for Shor's algorithm using 2n+3 qubits.*
#     Quantum Information and Computation, Vol. 3, No. 2 (2003) pp. 175-185.
#
# .. [#Draper2000]
#
#     Thomas G. Draper (2000) *Addition on a Quantum Computer.*
#     arXiv preprint, arXiv:quant-ph/0008033.
#
# About the author
# ----------------
# .. include:: ../_static/authors/olivia_di_matteo.txt
