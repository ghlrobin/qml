r"""Amplitude Amplification and beyond
=============================================================

Amplitude Amplification is a technique widely studied and used in different contexts. Grover's algorithm, for instance,
is a particular case of this technique. In this tutorial you will understand
the simple case but also you will learn how to use some of its more powerful variants: Fixed-Point Amplitude Amplification
and Oblivious Amplitude Amplification.


Amplitude Amplification
--------------------------

The first thing to do is to define the problem we want to solve. Given a state
:math:`|\Psi\rangle = \alpha |\phi\rangle + \beta|\phi^{\perp}\rangle` represented as the sum of two orthogonal states,
we look for a method that amplifies the state :math:`|\phi\rangle`. In other words, what we will do is to increase
the amplitude of :math:`\alpha` -- hence the name *Amplitude Amplification*.
For this, we are given two ingredients:

- An operator :math:`U` that generates the initial state: :math:`U|0\rangle = |\Psi\rangle`.

- An oracle :math:`mathcal{O}` that marks the state to amplify:

  .. math::

    \begin{cases}
    \mathcal{O}|\phi\rangle = -|\phi\rangle, \\
    \mathcal{O}|\phi^{\perp}\rangle = |\phi^{\perp}\rangle.
    \end{cases}

With these two operations we can generate a series of reflections that will help us to amplify the desired state.
To understand how, we draw the two-dimensional space generated by the states
:math:`|\phi\rangle` and :math:`|\phi^{\perp}\rangle`. We represent the state :math:`|\Psi\rangle` as a vector
in this space and we will see how the reflections generated by the operators :math:`U` and :math:`\mathcal{O}` help us.

.. figure:: ../_static/demonstration_assets/amplitude_amplification/amp_amp.jpeg
    :align: center
    :width: 50%

Thanks to this two reflections, we managed to bring the current state closer to our target.

The first reflection is equivalent to applying the oracle since it changes the sign only of the :math:`|\phi\rangle`
component. The second reflection has to be done with respect to the state :math:`|\Psi\rangle` and is something we
can do with the PennyLane operator `qml.Reflection(U)`.
These two reflections are equivalent to rotating :math:`2 \theta` degrees the initial state through the circunference.

Let us consider an example where :math:`\alpha|\phi^{\perp}\rangle = \frac{1}{2}|01\rangle` and
:math:`\beta |\phi^{\perp}\rangle = \frac{1}{2}(|00\rangle + |10\rangle + |11\rangle)`.
In this case we have that :math:`U = H^{\otimes 2}` and the oracle is the operator that changes sign to the
state :math:`|01\rangle`.

"""

import pennylane as qml
import matplotlib.pyplot as plt
plt.style.use('pennylane.drawer.plot')

@qml.prod
def U(wires):
  qml.Hadamard(wires = wires[0])
  qml.Hadamard(wires = wires[1])

# This oracle would be already given to us
# We don't know what element it marks and we want to discover it.
@qml.prod
def O(wires):
  qml.FlipSign([0,1], wires = wires)

dev = qml.device("default.qubit")

@qml.qnode(dev)
def circuit():

  # Generate the initial state
  U(wires = range(2))

  # Apply the first reflection
  O(wires = range(2))

  # Apply the second reflection
  qml.Reflection(U(wires = range(2)))

  return qml.probs(wires = range(2))

output = circuit()
plt.bar(["00","01", "10", "11"], output)
plt.show()

##############################################################################
#
# We have managed to amplify the desired state. In this case with one iteration has been enough but in
# general we will have to repeat this procedure :math:`\text{iters}` times where:
#
# .. math::
#
#   \text{iters} \sim \frac{\pi}{4 \arcsin \alpha}-\frac{1}{2}.
#
# Note that for our case :math:`\alpha = \frac{1}{2}` it is satisfied that :math:`\text{iters} = 1`.
#
# Fixed-Point Quantum Search
# ---------------------------
#
# So far we have shown what we can define as the textbook Amplitude Amplification. This template is already given in
# Pennylane and we could rewrite the previous code as follows:

@qml.qnode(dev)
def circuit(iters = 1):

  # Generate the initial state
  U(wires = range(2))

  # Apply Amplitude Amplification
  qml.AmplitudeAmplification(
      U = U(wires = range(2)),
      O = O(wires = range(2)),
      iters = iters
  )

  return qml.probs(wires = range(2))

##############################################################################
# However, the reality is not always so easy and in many occasions, we want to amplify the
# state :math:`|\phi\rangle` but we do not know the value of :math:`\alpha` that accompanies it.
# This is a limitation since we cannot calculate the number of iterations we must execute.
# Let's see the consequences of setting an unsuitable :math:`\text{iters}` value:

output = circuit(iters = 3)

plt.bar(["00","01", "10", "11"], output)
plt.show()

##############################################################################
# This graph shows how no state has been amplified. Visually, the problem can be understood, since too many iterations
# cause the state to rotate too much and move away from the desired state.
#
#.. figure:: ../_static/demonstration_assets/amplitude_amplification/overcook.jpeg
#    :align: center
#    :width: 50%
#
# To solve this problem, an algorithm known as Fixed-Point Quantum Search was developed, which ensures that the
# probability of success does not decrease by adding extra iterations.
# This variant can be coded in PennyLane as follows:

@qml.qnode(dev)
def circuit(iters):

  # Generate the initial state
  U(wires = range(2))

  # Apply Fixed-Point Amplitude Amplification
  qml.AmplitudeAmplification(
      U = U(wires = range(2)),
      O = O(wires = range(2)),
      fixed_point=True,
      work_wire = 2, # We need an extra wire
      iters = iters
  )

  return qml.probs(wires = range(2))

output = circuit(iters = 3)
plt.bar(["00","01", "10", "11"], output)
plt.show()

##############################################################################
# We have managed to maintain a high probability in the solution. Next we show the probability of success as a
# function of the number of iterations:

iter_range = range(1, 21, 2)

probs = []

for iter in iter_range:
    probs.append(circuit(iter)[1])

plt.plot(iter_range, [0.9] * len(iter_range))
plt.plot(iter_range, probs, label="fixed-point variant")
plt.xlabel("Iters")
plt.ylabel("Success prob")
plt.legend()
plt.show()

##############################################################################
# The probability of success, once the value of :math:`0.9` is reached, is maintained regardless of the number of
# iterations. This value can be modified by specifying `p_min` as an attribute in `qml.AmplitudeAmplification`.
# To learn more about this algorithm, please refer to this paper.
#
# Oblivious Amplitude Amplification
# ---------------------------------
#
# Another advanced variant within this field is *Oblivious Amplitude Amplification* which is able to solve the following
# problem. We are given an operator :math:`U` such that
#
# .. math::
#
#   U|0\rangle^{\otimes m}|\phi\rangle = \alpha|0\rangle^{\otimes m} V|\phi\rangle + \beta|\phi^{\perp}\rangle
#
# for a certain unitary :math:`V` and for any state :math:`|\phi\rangle`. The goal is to achieve amplification of the
# state :math:`|0\rangle^{\otimes m} V|phi\rangle`. The important thing about this variant is that we do not need to
# know the state :math:`|\phi\rangle` to amplify it, we will work *obliviously*. In this method the oracle that will
# be used is the operator that changes the sign of :math:`|0\rangle^{\otimes m}`. In addition we will have to indicate
# to the operator which are these :math`m` qubits which we call `reflection_wires`.
#
# Let's see an example with :math:`V = X` and :math:`|\phi\rangle = |1\rangle`. We will try to
# amplify :math:`|0\rangle X|1\rangle`:

import numpy as np

@qml.prod
def U(wires):
  # U|0⟩|ϕ⟩ = 1/2 |0⟩X|ϕ⟩ + √3/2 |1⟩|ϕ⟩
  qml.RY(2*np.pi / 3, wires = wires[0])
  qml.PauliX(wires = wires[0])
  qml.CNOT(wires = wires)
  qml.PauliX(wires = wires[0])

@qml.qnode(dev)
def circuit(iters):

  # Generate the initial state
  qml.PauliX(1) # Let's take |ϕ⟩=|1⟩
  U(wires = range(2))


  # Apply Oblivious Amplitude Amplification
  qml.AmplitudeAmplification(
      U = U(wires = range(2)),
      O = qml.FlipSign(0, wires = [0]),
      reflection_wires = [0],
      iters = iters
  )

  return qml.probs(wires = range(2))

output = circuit(iters = 1)
plt.bar(["00","01", "10", "11"], output)
plt.show()

##############################################################################
# The obtained state is :math:`|00\rangle` which is just the value :math:`|0\rangle X|1\rangle`. As you can see,
# the operator `qml.AmplitudeAmplification` has not used any information about the state :math:`|\phi\rangle`.
# To understand in depth how this algorithm works see this paper.
#
# Conclusion
# ----------
# In this tutorial we have shown that there are Amplitude Amplification related techniques beyond Grover's algorithm.
# We have shown how to use them and invite the reader to go deeper into all of them or use the tools shown to generate
# new ideas.
#
# About the author
# ----------------
#